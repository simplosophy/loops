use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component as PathComponent, Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use chrono::Utc;
use serde_json::{Map, Value, json};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::process::{Child, Command};
use tokio::sync::Mutex as AsyncMutex;
use tokio::time::{Instant, timeout};
use uuid::Uuid;

use crate::loop0::config::PolicyConfig;
use crate::loop0::provider::ToolProfile;
use crate::loop0::tool::ToolResult;
use crate::loop0::types::ToolCall;

const COMMON_EXECUTABLE_DIRS: &[&str] = &[
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
];

pub fn shell_tool_profile() -> ToolProfile {
    ToolProfile {
        name: "shell".to_string(),
        description: "Execute shell commands or manage background shell sessions.".to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["run", "list", "poll", "log", "write", "kill"]},
                "command": {"type": "string"},
                "commands": {"type": "array", "items": {"type": "string"}},
                "background": {"type": "boolean", "default": false},
                "session_id": {"type": "string"},
                "cwd": {"type": "string"},
                "working_directory": {"type": "string"},
                "env": {"type": "object", "additionalProperties": {"type": "string"}},
                "timeout_seconds": {"type": "number"},
                "timeout_ms": {"type": "number"},
                "max_output_chars": {"type": "integer"},
                "max_output_length": {"type": "integer"},
                "offset": {"type": "integer"},
                "limit": {"type": "integer"},
                "data": {"type": "string"},
                "eof": {"type": "boolean"}
            },
            "required": ["op"]
        }),
    }
}

#[derive(Clone, Default)]
pub struct ShellProcessManager {
    sessions: Arc<StdMutex<BTreeMap<String, Arc<ShellSession>>>>,
}

impl ShellProcessManager {
    async fn start(
        &self,
        command: &str,
        cwd: &Path,
        env: Option<&BTreeMap<String, String>>,
    ) -> Result<Arc<ShellSession>> {
        let mut child = shell_command(command, cwd, env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| format!("failed to spawn background shell command: {command}"))?;
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        let session = Arc::new(ShellSession {
            session_id: format!("sh_{}", Uuid::new_v4().simple()),
            command: command.to_string(),
            started_at: Utc::now(),
            completed_at: StdMutex::new(None),
            returncode: StdMutex::new(None),
            log_entries: StdMutex::new(Vec::new()),
            child: AsyncMutex::new(child),
        });
        self.sessions
            .lock()
            .expect("shell sessions mutex poisoned")
            .insert(session.session_id.clone(), session.clone());
        if let Some(stdout) = stdout {
            tokio::spawn(read_session_stream(session.clone(), stdout, "stdout"));
        }
        if let Some(stderr) = stderr {
            tokio::spawn(read_session_stream(session.clone(), stderr, "stderr"));
        }
        Ok(session)
    }

    async fn list(&self) -> Result<Vec<Value>> {
        let sessions = self
            .sessions
            .lock()
            .expect("shell sessions mutex poisoned")
            .values()
            .cloned()
            .collect::<Vec<_>>();
        let mut values = Vec::new();
        for session in sessions {
            values.push(session.as_json().await?);
        }
        Ok(values)
    }

    async fn poll(&self, session_id: &str) -> Result<Value> {
        self.require(session_id)?.as_json().await
    }

    fn log(&self, session_id: &str, offset: usize, limit: usize) -> Result<Value> {
        let session = self.require(session_id)?;
        let entries = session
            .log_entries
            .lock()
            .expect("shell log mutex poisoned");
        let normalized_offset = offset;
        let normalized_limit = limit.max(1);
        let lines = entries
            .iter()
            .skip(normalized_offset)
            .take(normalized_limit)
            .map(|entry| {
                json!({
                    "index": entry.index,
                    "stream": entry.stream,
                    "text": entry.text,
                    "created_at": entry.created_at.to_rfc3339(),
                })
            })
            .collect::<Vec<_>>();
        Ok(json!({
            "session_id": session_id,
            "offset": normalized_offset,
            "next_offset": normalized_offset + lines.len(),
            "total": entries.len(),
            "lines": lines,
        }))
    }

    async fn write(&self, session_id: &str, data: &str, eof: bool) -> Result<Value> {
        let session = self.require(session_id)?;
        let mut child = session.child.lock().await;
        let Some(stdin) = child.stdin.as_mut() else {
            return Err(anyhow!("session stdin is not available"));
        };
        stdin.write_all(data.as_bytes()).await?;
        stdin.flush().await?;
        if eof {
            child.stdin.take();
        }
        Ok(json!({
            "session_id": session_id,
            "bytes_written": data.len(),
            "eof": eof,
        }))
    }

    async fn kill(&self, session_id: &str) -> Result<Value> {
        let session = self.require(session_id)?;
        {
            let mut child = session.child.lock().await;
            if current_returncode(&session).is_none() {
                let _ = child.start_kill();
                if let Ok(status) = child.wait().await {
                    set_completed(&session, status.code());
                }
            }
        }
        session.as_json().await
    }

    fn require(&self, session_id: &str) -> Result<Arc<ShellSession>> {
        self.sessions
            .lock()
            .expect("shell sessions mutex poisoned")
            .get(session_id)
            .cloned()
            .ok_or_else(|| anyhow!("unknown shell session: {session_id}"))
    }
}

struct ShellSession {
    session_id: String,
    command: String,
    started_at: chrono::DateTime<chrono::Utc>,
    completed_at: StdMutex<Option<chrono::DateTime<chrono::Utc>>>,
    returncode: StdMutex<Option<i32>>,
    log_entries: StdMutex<Vec<ShellLogEntry>>,
    child: AsyncMutex<Child>,
}

impl ShellSession {
    async fn as_json(self: &Arc<Self>) -> Result<Value> {
        self.refresh_status().await?;
        let returncode = current_returncode(self);
        let completed_at = self
            .completed_at
            .lock()
            .expect("shell session completed_at mutex poisoned")
            .map(|value| value.to_rfc3339());
        Ok(json!({
            "session_id": self.session_id,
            "command": self.command,
            "running": returncode.is_none(),
            "returncode": returncode,
            "started_at": self.started_at.to_rfc3339(),
            "completed_at": completed_at,
        }))
    }

    async fn refresh_status(self: &Arc<Self>) -> Result<()> {
        if current_returncode(self).is_some() {
            return Ok(());
        }
        let mut child = self.child.lock().await;
        if let Some(status) = child.try_wait()? {
            set_completed(self, status.code());
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct ShellLogEntry {
    index: usize,
    stream: String,
    text: String,
    created_at: chrono::DateTime<chrono::Utc>,
}

async fn read_session_stream<R>(session: Arc<ShellSession>, mut reader: R, stream: &'static str)
where
    R: AsyncRead + Unpin + Send + 'static,
{
    let mut buffer = [0_u8; 4096];
    loop {
        let read = match reader.read(&mut buffer).await {
            Ok(0) | Err(_) => break,
            Ok(read) => read,
        };
        let text = String::from_utf8_lossy(&buffer[..read]).to_string();
        let mut entries = session
            .log_entries
            .lock()
            .expect("shell log mutex poisoned");
        let index = entries.len();
        entries.push(ShellLogEntry {
            index,
            stream: stream.to_string(),
            text,
            created_at: Utc::now(),
        });
    }
}

pub async fn execute_shell_tool(
    tool_call: &ToolCall,
    workspace: &Path,
    policy: &PolicyConfig,
    manager: &ShellProcessManager,
) -> Result<ToolResult> {
    let args = tool_call.arguments.as_object().ok_or_else(|| {
        anyhow!(
            "shell arguments must be an object, got {}",
            tool_call.arguments
        )
    })?;
    let op = first_string(args, &["op"]).unwrap_or_else(|| "run".to_string());
    match op.trim().to_lowercase().as_str() {
        "run" => run_shell(args, workspace, policy, manager).await,
        "list" => json_result(
            json!({"sessions": manager.list().await?}),
            metadata([("op", json!("list"))]),
        ),
        "poll" => {
            let session_id = required_string(args, "session_id")?;
            json_result(
                manager.poll(&session_id).await?,
                metadata([("op", json!("poll")), ("session_id", json!(session_id))]),
            )
        }
        "log" => {
            let session_id = required_string(args, "session_id")?;
            let offset = first_usize(args, &["offset"]).unwrap_or(0);
            let limit = first_usize(args, &["limit"]).unwrap_or(100);
            json_result(
                manager.log(&session_id, offset, limit)?,
                metadata([("op", json!("log")), ("session_id", json!(session_id))]),
            )
        }
        "write" => {
            let session_id = required_string(args, "session_id")?;
            let data = first_string(args, &["data"]).unwrap_or_default();
            let eof = first_bool(args, &["eof"]).unwrap_or(false);
            json_result(
                manager.write(&session_id, &data, eof).await?,
                metadata([("op", json!("write")), ("session_id", json!(session_id))]),
            )
        }
        "kill" => {
            let session_id = required_string(args, "session_id")?;
            json_result(
                manager.kill(&session_id).await?,
                metadata([("op", json!("kill")), ("session_id", json!(session_id))]),
            )
        }
        other => Ok(ToolResult::failure(
            format!("Unknown shell op: {other}"),
            "invalid_args",
        )),
    }
}

async fn run_shell(
    args: &Map<String, Value>,
    workspace: &Path,
    policy: &PolicyConfig,
    manager: &ShellProcessManager,
) -> Result<ToolResult> {
    let commands = match commands_from_args(args) {
        Ok(commands) => commands,
        Err(error) => return Ok(ToolResult::failure(error.to_string(), "invalid_args")),
    };
    let env = match env_from_args(args) {
        Ok(env) => env,
        Err(error) => return Ok(ToolResult::failure(error.to_string(), "invalid_args")),
    };
    let timeout_seconds = match timeout_seconds_from_args(args, policy.shell_timeout_seconds) {
        Ok(timeout) => timeout,
        Err(error) => return Ok(ToolResult::failure(error.to_string(), "invalid_args")),
    };
    let max_output_chars = max_output_chars_from_args(args, policy.shell_max_output_chars);
    let background = first_bool(args, &["background"]).unwrap_or(false);
    if background && commands.len() != 1 {
        return Ok(ToolResult::failure(
            "shell.run background sessions require exactly one command",
            "invalid_args",
        ));
    }
    for command in &commands {
        if let Err(reason) = validate_command(command) {
            return Ok(ToolResult::failure_with_metadata(
                format!("Blocked: {reason}"),
                "blocked",
                metadata([
                    ("op", json!("run")),
                    ("command", json!(command)),
                    ("commands", json!(commands)),
                ]),
            ));
        }
    }
    let workspace = normalize_path(workspace);
    std::fs::create_dir_all(&workspace)
        .with_context(|| format!("failed to create shell workspace {}", workspace.display()))?;
    let cwd = resolve_cwd(args, &workspace);
    let external_paths = external_paths(&commands, &cwd, &workspace);
    if !external_paths.is_empty() && policy.shell_external_path_policy == "deny" {
        return Ok(blocked_result(
            "Shell command references paths outside the workspace: ",
            &commands,
            &external_paths,
            background,
        ));
    }
    if !external_paths.is_empty()
        && policy.shell_external_path_policy == "ask"
        && !policy.auto_approve
    {
        return Ok(blocked_result(
            "Shell command references paths outside the workspace: ",
            &commands,
            &external_paths,
            background,
        ));
    }
    if background && policy.shell_require_approval_for_background && !policy.auto_approve {
        return Ok(ToolResult::failure_with_metadata(
            "Blocked: Background shell sessions require approval.",
            "blocked",
            metadata([
                ("op", json!("run")),
                ("command", json!(commands[0])),
                ("commands", json!(commands)),
                ("background", json!(true)),
                ("cwd", json!(cwd.display().to_string())),
            ]),
        ));
    }
    if !cwd.exists() || !cwd.is_dir() {
        return Ok(ToolResult::failure_with_metadata(
            format!(
                "shell.run cwd does not exist or is not a directory: {}",
                cwd.display()
            ),
            "invalid_args",
            metadata([
                ("op", json!("run")),
                ("cwd", json!(cwd.display().to_string())),
            ]),
        ));
    }
    if background {
        let command = &commands[0];
        let session = manager.start(command, &cwd, env.as_ref()).await?;
        return json_result(
            json!({
                "session_id": session.session_id,
                "status": "started",
                "command": command,
            }),
            run_metadata(
                &commands,
                &[],
                true,
                &cwd,
                timeout_seconds,
                max_output_chars,
                env.as_ref(),
            )
            .into_iter()
            .chain([
                ("session_id".to_string(), json!(session.session_id)),
                ("returncode".to_string(), Value::Null),
            ])
            .collect(),
        );
    }
    let mut outputs = Vec::new();
    let deadline = Instant::now() + Duration::from_secs_f64(timeout_seconds);
    for command in &commands {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            outputs.push(ShellCommandOutput::timeout(command));
        } else {
            outputs.push(run_command(command, &cwd, env.as_ref(), remaining).await?);
        }
        let latest = outputs.last().expect("just pushed shell command output");
        if latest.status() == "timeout" || latest.exit_code().is_some_and(|code| code != 0) {
            break;
        }
    }
    let output = render_command_outputs(&outputs, max_output_chars);
    let metadata = run_metadata(
        &commands,
        &outputs,
        false,
        &cwd,
        timeout_seconds,
        max_output_chars,
        env.as_ref(),
    );
    if outputs
        .iter()
        .all(|output| output.status() != "timeout" && output.exit_code().unwrap_or(0) == 0)
    {
        return Ok(ToolResult::success_with_metadata(output, metadata));
    }
    let status = if outputs.iter().any(|output| output.status() == "timeout") {
        "timeout"
    } else {
        "error"
    };
    Ok(ToolResult::failure_with_metadata(output, status, metadata))
}

fn blocked_result(
    prefix: &str,
    commands: &[String],
    external_paths: &[String],
    background: bool,
) -> ToolResult {
    ToolResult::failure_with_metadata(
        format!("Blocked: {prefix}{}", external_paths.join(", ")),
        "blocked",
        metadata([
            ("op", json!("run")),
            ("command", json!(single_command(commands))),
            ("commands", json!(commands)),
            ("background", json!(background)),
            ("external_paths", json!(external_paths)),
        ]),
    )
}

#[derive(Debug, Clone)]
struct ShellCommandOutput {
    command: String,
    stdout: String,
    stderr: String,
    outcome: ShellCommandOutcome,
}

impl ShellCommandOutput {
    fn timeout(command: &str) -> Self {
        Self {
            command: command.to_string(),
            stdout: String::new(),
            stderr: String::new(),
            outcome: ShellCommandOutcome::Timeout,
        }
    }

    fn status(&self) -> &'static str {
        match self.outcome {
            ShellCommandOutcome::Timeout => "timeout",
            ShellCommandOutcome::Exit { .. } => "completed",
        }
    }

    fn exit_code(&self) -> Option<i32> {
        match self.outcome {
            ShellCommandOutcome::Exit { code } => code,
            ShellCommandOutcome::Timeout => None,
        }
    }

    fn as_json(&self) -> Value {
        let mut payload = Map::new();
        payload.insert("command".to_string(), json!(self.command));
        payload.insert("stdout".to_string(), json!(self.stdout));
        payload.insert("stderr".to_string(), json!(self.stderr));
        payload.insert("status".to_string(), json!(self.status()));
        match self.outcome {
            ShellCommandOutcome::Exit { code } => {
                payload.insert(
                    "outcome".to_string(),
                    json!({"type": "exit", "exit_code": code}),
                );
                if let Some(code) = code {
                    payload.insert("exit_code".to_string(), json!(code));
                }
            }
            ShellCommandOutcome::Timeout => {
                payload.insert("outcome".to_string(), json!({"type": "timeout"}));
            }
        }
        Value::Object(payload)
    }
}

#[derive(Debug, Clone, Copy)]
enum ShellCommandOutcome {
    Exit { code: Option<i32> },
    Timeout,
}

async fn run_command(
    command: &str,
    cwd: &Path,
    env: Option<&BTreeMap<String, String>>,
    timeout_duration: Duration,
) -> Result<ShellCommandOutput> {
    let mut child = shell_command(command, cwd, env)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("failed to spawn shell command: {command}"))?;
    let mut stdout = child.stdout.take().context("failed to capture stdout")?;
    let mut stderr = child.stderr.take().context("failed to capture stderr")?;
    let stdout_task = tokio::spawn(async move {
        let mut buffer = Vec::new();
        stdout.read_to_end(&mut buffer).await.map(|_| buffer)
    });
    let stderr_task = tokio::spawn(async move {
        let mut buffer = Vec::new();
        stderr.read_to_end(&mut buffer).await.map(|_| buffer)
    });
    let outcome = match timeout(timeout_duration, child.wait()).await {
        Ok(status) => ShellCommandOutcome::Exit {
            code: status.context("failed to wait for shell command")?.code(),
        },
        Err(_) => {
            let _ = child.start_kill();
            let _ = child.wait().await;
            ShellCommandOutcome::Timeout
        }
    };
    let stdout = stdout_task
        .await
        .context("stdout task failed")?
        .context("failed to read stdout")?;
    let stderr = stderr_task
        .await
        .context("stderr task failed")?
        .context("failed to read stderr")?;
    Ok(ShellCommandOutput {
        command: command.to_string(),
        stdout: String::from_utf8_lossy(&stdout).to_string(),
        stderr: String::from_utf8_lossy(&stderr).to_string(),
        outcome,
    })
}

fn shell_command<'a>(
    command: &'a str,
    cwd: &'a Path,
    env: Option<&'a BTreeMap<String, String>>,
) -> Command {
    let mut process = Command::new("sh");
    process.arg("-c").arg(command).current_dir(cwd);
    if let Some(env) = env {
        process.envs(env);
    }
    process
}

fn run_metadata(
    commands: &[String],
    outputs: &[ShellCommandOutput],
    background: bool,
    cwd: &Path,
    timeout_seconds: f64,
    max_output_chars: usize,
    env: Option<&BTreeMap<String, String>>,
) -> BTreeMap<String, Value> {
    let mut metadata = metadata([
        ("op", json!("run")),
        ("command", json!(single_command(commands))),
        ("commands", json!(commands)),
        ("command_count", json!(commands.len())),
        ("background", json!(background)),
        ("cwd", json!(cwd.display().to_string())),
        ("timeout_seconds", json!(timeout_seconds)),
        ("max_output_chars", json!(max_output_chars)),
        (
            "returncode",
            outputs
                .last()
                .and_then(ShellCommandOutput::exit_code)
                .map(Value::from)
                .unwrap_or(Value::Null),
        ),
        (
            "stdout_chars",
            json!(
                outputs
                    .iter()
                    .map(|output| output.stdout.chars().count())
                    .sum::<usize>()
            ),
        ),
        (
            "stderr_chars",
            json!(
                outputs
                    .iter()
                    .map(|output| output.stderr.chars().count())
                    .sum::<usize>()
            ),
        ),
        (
            "outputs",
            Value::Array(outputs.iter().map(ShellCommandOutput::as_json).collect()),
        ),
    ]);
    if let Some(env) = env {
        metadata.insert(
            "env_keys".to_string(),
            Value::Array(env.keys().cloned().map(Value::String).collect()),
        );
    }
    metadata
}

fn commands_from_args(args: &Map<String, Value>) -> Result<Vec<String>> {
    if let Some(value) = args.get("commands") {
        let Some(commands) = value.as_array() else {
            return Err(anyhow!(
                "shell.run commands must be a sequence of command strings"
            ));
        };
        let commands = commands
            .iter()
            .filter_map(|value| value.as_str().map(str::trim))
            .filter(|value| !value.is_empty())
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        if commands.is_empty() {
            return Err(anyhow!("shell.run requires command or commands"));
        }
        return Ok(commands);
    }
    let command = first_string(args, &["command"]).unwrap_or_default();
    if command.trim().is_empty() {
        return Err(anyhow!("shell.run requires command or commands"));
    }
    Ok(vec![command.trim().to_string()])
}

fn env_from_args(args: &Map<String, Value>) -> Result<Option<BTreeMap<String, String>>> {
    let Some(value) = args.get("env") else {
        return Ok(None);
    };
    let Some(object) = value.as_object() else {
        return Err(anyhow!("shell.run env must be an object"));
    };
    let mut env = BTreeMap::new();
    for (key, value) in object {
        if key.is_empty() {
            return Err(anyhow!("shell.run env keys must be non-empty"));
        }
        if value.is_null() {
            continue;
        }
        env.insert(key.clone(), value.as_str().unwrap_or("").to_string());
    }
    Ok(Some(env))
}

fn timeout_seconds_from_args(args: &Map<String, Value>, default: f64) -> Result<f64> {
    let timeout_seconds = first_f64(args, &["timeout_seconds"])
        .or_else(|| first_f64(args, &["timeout_ms", "timeoutMs"]).map(|value| value / 1000.0))
        .unwrap_or(default);
    if timeout_seconds <= 0.0 {
        return Err(anyhow!("shell.run timeout must be greater than zero"));
    }
    Ok(timeout_seconds)
}

fn max_output_chars_from_args(args: &Map<String, Value>, default: usize) -> usize {
    first_usize(
        args,
        &["max_output_chars", "max_output_length", "maxOutputLength"],
    )
    .unwrap_or(default)
}

fn resolve_cwd(args: &Map<String, Value>, workspace: &Path) -> PathBuf {
    let Some(raw) = first_string(args, &["cwd", "working_directory", "workingDirectory"]) else {
        return workspace.to_path_buf();
    };
    if raw.trim().is_empty() {
        return workspace.to_path_buf();
    }
    let path = expand_home(PathBuf::from(raw.trim()));
    normalize_path(if path.is_absolute() {
        path
    } else {
        workspace.join(path)
    })
}

fn validate_command(command: &str) -> std::result::Result<(), String> {
    let lower = command.to_lowercase();
    if lower.contains("rm -rf /") || lower.contains("rm -fr /") {
        return Err("command matches a blocked security pattern".to_string());
    }
    if lower.contains(":()") {
        return Err("command matches a blocked security pattern".to_string());
    }
    if (lower.contains("curl") || lower.contains("wget"))
        && lower.contains('|')
        && (lower.contains(" sh") || lower.contains(" bash") || lower.contains(" zsh"))
    {
        return Err("command matches a blocked security pattern".to_string());
    }
    let blocked_commands = BTreeSet::from([
        "sudo", "su", "doas", "pkexec", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt",
        "poweroff", "chmod", "chown", "mount", "umount",
    ]);
    for segment in split_shell_segments(command) {
        let tokens =
            shell_words(&segment).map_err(|error| format!("command parse error: {error}"))?;
        if let Some(first) = tokens.first() {
            let base = Path::new(first)
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or(first);
            if blocked_commands.contains(base) {
                return Err(format!("command '{base}' is blocked"));
            }
        }
    }
    Ok(())
}

fn external_paths(commands: &[String], cwd: &Path, workspace: &Path) -> Vec<String> {
    let workspace = normalize_path(workspace);
    let cwd = normalize_path(cwd);
    let mut paths = BTreeSet::new();
    if !is_relative_to(&cwd, &workspace) {
        paths.insert(cwd.display().to_string());
    }
    for command in commands {
        for segment in split_shell_segments(command) {
            let Ok(tokens) = shell_words(&segment) else {
                continue;
            };
            for (index, token) in tokens.iter().enumerate() {
                if !looks_like_path(token) {
                    continue;
                }
                let path = expand_home(PathBuf::from(token));
                if index == 0
                    && path
                        .parent()
                        .and_then(Path::to_str)
                        .is_some_and(|parent| COMMON_EXECUTABLE_DIRS.contains(&parent))
                {
                    continue;
                }
                let resolved = normalize_path(if path.is_absolute() {
                    path
                } else {
                    cwd.join(path)
                });
                if !is_relative_to(&resolved, &workspace) {
                    paths.insert(resolved.display().to_string());
                }
            }
        }
    }
    paths.into_iter().collect()
}

fn split_shell_segments(command: &str) -> Vec<String> {
    command
        .split(|ch| matches!(ch, ';' | '|' | '\n' | '&'))
        .map(str::trim)
        .filter(|segment| !segment.is_empty() && !segment.starts_with('#'))
        .map(ToString::to_string)
        .collect()
}

fn shell_words(segment: &str) -> std::result::Result<Vec<String>, String> {
    let mut words = Vec::new();
    let mut current = String::new();
    let mut chars = segment.chars().peekable();
    let mut quote = None;
    while let Some(ch) = chars.next() {
        match ch {
            '\\' => {
                if let Some(next) = chars.next() {
                    current.push(next);
                }
            }
            '\'' | '"' if quote == Some(ch) => quote = None,
            '\'' | '"' if quote.is_none() => quote = Some(ch),
            ch if ch.is_whitespace() && quote.is_none() => {
                if !current.is_empty() {
                    words.push(std::mem::take(&mut current));
                }
            }
            _ => current.push(ch),
        }
    }
    if let Some(quote) = quote {
        return Err(format!("unterminated quote {quote}"));
    }
    if !current.is_empty() {
        words.push(current);
    }
    Ok(words)
}

fn looks_like_path(token: &str) -> bool {
    if token.is_empty() || token.starts_with('-') || is_uri(token) {
        return false;
    }
    matches!(token, "." | ".." | "~")
        || token.starts_with('/')
        || token.starts_with("./")
        || token.starts_with("../")
        || token.starts_with("~/")
}

fn is_uri(token: &str) -> bool {
    let Some((scheme, _)) = token.split_once("://") else {
        return false;
    };
    let mut chars = scheme.chars();
    chars.next().is_some_and(|ch| ch.is_ascii_alphabetic())
        && chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '+' | '-' | '.'))
}

fn render_command_outputs(outputs: &[ShellCommandOutput], max_chars: usize) -> String {
    if outputs.is_empty() {
        return "(no output)".to_string();
    }
    if max_chars == 0 {
        return String::new();
    }
    let include_command = outputs.len() > 1;
    let mut text = outputs
        .iter()
        .map(|output| render_command_output(output, include_command))
        .collect::<Vec<_>>()
        .join("\n\n");
    if text.chars().count() > max_chars {
        text = text.chars().take(max_chars).collect::<String>();
        text = text.trim_end_matches('\n').to_string();
        text.push_str("\n... [output truncated]");
    }
    text
}

fn render_command_output(output: &ShellCommandOutput, include_command: bool) -> String {
    let mut lines = Vec::new();
    if include_command {
        lines.push(format!("$ {}", output.command));
    }
    let stdout = output.stdout.trim_end_matches('\n');
    let stderr = output.stderr.trim_end_matches('\n');
    if !stdout.is_empty() {
        lines.push(stdout.to_string());
    }
    if !stderr.is_empty() {
        if !stdout.is_empty() {
            lines.push(String::new());
        }
        lines.push("stderr:".to_string());
        lines.push(stderr.to_string());
    }
    if let Some(code) = output.exit_code() {
        if code != 0 {
            lines.push(format!("exit code: {code}"));
        }
    }
    if output.status() == "timeout" {
        lines.push("status: timeout".to_string());
    }
    let text = lines.join("\n").trim().to_string();
    if text.is_empty() {
        "(no output)".to_string()
    } else {
        text
    }
}

fn normalize_path(path: impl AsRef<Path>) -> PathBuf {
    let path = path.as_ref();
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            PathComponent::CurDir => {}
            PathComponent::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    normalized
}

fn expand_home(path: PathBuf) -> PathBuf {
    let raw = path.to_string_lossy();
    if raw == "~" {
        return std::env::var_os("HOME").map(PathBuf::from).unwrap_or(path);
    }
    if let Some(rest) = raw.strip_prefix("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return PathBuf::from(home).join(rest);
        }
    }
    path
}

fn is_relative_to(path: &Path, parent: &Path) -> bool {
    path.strip_prefix(parent).is_ok()
}

fn first_string(args: &Map<String, Value>, names: &[&str]) -> Option<String> {
    names.iter().find_map(|name| {
        args.get(*name)
            .and_then(Value::as_str)
            .map(ToString::to_string)
    })
}

fn required_string(args: &Map<String, Value>, name: &str) -> Result<String> {
    let value = args
        .get(name)
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .to_string();
    if value.is_empty() {
        return Err(anyhow!("shell op requires {name}"));
    }
    Ok(value)
}

fn first_bool(args: &Map<String, Value>, names: &[&str]) -> Option<bool> {
    names
        .iter()
        .find_map(|name| args.get(*name).and_then(Value::as_bool))
}

fn first_f64(args: &Map<String, Value>, names: &[&str]) -> Option<f64> {
    names
        .iter()
        .find_map(|name| args.get(*name).and_then(Value::as_f64))
}

fn first_usize(args: &Map<String, Value>, names: &[&str]) -> Option<usize> {
    names.iter().find_map(|name| {
        args.get(*name)
            .and_then(Value::as_u64)
            .map(|value| value as usize)
    })
}

fn json_result(payload: Value, metadata: BTreeMap<String, Value>) -> Result<ToolResult> {
    Ok(ToolResult::success_with_metadata(
        serde_json::to_string(&payload)?,
        metadata,
    ))
}

fn metadata<const N: usize>(items: [(&str, Value); N]) -> BTreeMap<String, Value> {
    items
        .into_iter()
        .map(|(key, value)| (key.to_string(), value))
        .collect()
}

fn single_command(commands: &[String]) -> Value {
    if commands.len() == 1 {
        Value::String(commands[0].clone())
    } else {
        Value::Null
    }
}

fn current_returncode(session: &ShellSession) -> Option<i32> {
    *session
        .returncode
        .lock()
        .expect("shell session returncode mutex poisoned")
}

fn set_completed(session: &ShellSession, code: Option<i32>) {
    *session
        .returncode
        .lock()
        .expect("shell session returncode mutex poisoned") = code.or(Some(-1));
    let mut completed_at = session
        .completed_at
        .lock()
        .expect("shell session completed_at mutex poisoned");
    if completed_at.is_none() {
        *completed_at = Some(Utc::now());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn renders_command_sequences_and_metadata() {
        let result = run_tool(
            json!({"op": "run", "commands": ["printf one", "printf two"]}),
            PolicyConfig::default(),
        )
        .await;

        assert!(result.is_success());
        assert_eq!(result.output, "$ printf one\none\n\n$ printf two\ntwo");
        assert_eq!(result.metadata["command_count"], 2);
        assert_eq!(result.metadata["returncode"], 0);
        assert_eq!(result.metadata["outputs"][0]["stdout"], "one");
    }

    #[tokio::test]
    async fn blocks_dangerous_and_external_paths() {
        let dangerous = run_tool(
            json!({"op": "run", "command": "rm -rf /"}),
            PolicyConfig::default(),
        )
        .await;
        assert_eq!(dangerous.status, "blocked");
        assert!(dangerous.error.unwrap().contains("Blocked:"));

        let external = run_tool(
            json!({"op": "run", "command": "cat /etc/passwd"}),
            PolicyConfig::default(),
        )
        .await;
        assert_eq!(external.status, "blocked");
        assert!(external.error.unwrap().contains("outside the workspace"));
    }

    #[tokio::test]
    async fn supports_background_sessions_and_logs() {
        let dir = tempfile_dir("background");
        let manager = ShellProcessManager::default();
        let mut policy = PolicyConfig::default();
        policy.shell_require_approval_for_background = false;
        let start = execute_shell_tool(
            &tool_call(json!({
                "op": "run",
                "command": "printf out; printf err >&2",
                "background": true
            })),
            &dir,
            &policy,
            &manager,
        )
        .await
        .unwrap();
        let payload: Value = serde_json::from_str(&start.output).unwrap();
        let session_id = payload["session_id"].as_str().unwrap();
        tokio::time::sleep(Duration::from_millis(50)).await;

        let list = execute_shell_tool(&tool_call(json!({"op": "list"})), &dir, &policy, &manager)
            .await
            .unwrap();
        let log = execute_shell_tool(
            &tool_call(json!({"op": "log", "session_id": session_id})),
            &dir,
            &policy,
            &manager,
        )
        .await
        .unwrap();
        let sessions: Value = serde_json::from_str(&list.output).unwrap();
        let log: Value = serde_json::from_str(&log.output).unwrap();

        assert!(
            sessions["sessions"]
                .as_array()
                .unwrap()
                .iter()
                .any(|session| session["session_id"] == session_id)
        );
        assert!(log["total"].as_u64().unwrap() >= 2);
        let streams = log["lines"]
            .as_array()
            .unwrap()
            .iter()
            .map(|line| line["stream"].as_str().unwrap())
            .collect::<BTreeSet<_>>();
        assert_eq!(streams, BTreeSet::from(["stdout", "stderr"]));
    }

    async fn run_tool(arguments: Value, policy: PolicyConfig) -> ToolResult {
        let dir = tempfile_dir("run");
        execute_shell_tool(
            &tool_call(arguments),
            &dir,
            &policy,
            &ShellProcessManager::default(),
        )
        .await
        .unwrap()
    }

    fn tool_call(arguments: Value) -> ToolCall {
        ToolCall {
            name: "shell".to_string(),
            arguments,
            id: "call".to_string(),
            raw: Value::Null,
        }
    }

    fn tempfile_dir(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!(
            "loops-rust-shell-{name}-{}",
            Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&path).unwrap();
        path
    }
}
