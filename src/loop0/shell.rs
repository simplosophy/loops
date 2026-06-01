use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use serde_json::{Value, json};
use tokio::io::AsyncReadExt;
use tokio::process::Command;
use tokio::time::timeout;

use crate::loop0::config::PolicyConfig;
use crate::loop0::provider::ToolProfile;
use crate::loop0::types::ToolCall;

pub fn shell_tool_profile() -> ToolProfile {
    ToolProfile {
        name: "shell".to_string(),
        description: "Execute shell commands inside the agent workspace.".to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["run"]},
                "command": {"type": "string"},
                "commands": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "number"}
            }
        }),
    }
}

pub async fn execute_shell_tool(
    tool_call: &ToolCall,
    workspace: &Path,
    policy: &PolicyConfig,
) -> Result<String> {
    let args = tool_call.arguments.as_object().ok_or_else(|| {
        anyhow!(
            "shell arguments must be an object, got {}",
            tool_call.arguments
        )
    })?;
    let op = args.get("op").and_then(Value::as_str).unwrap_or("run");
    if op != "run" {
        return Ok(json!({
            "status": "invalid_args",
            "error": format!("unsupported shell op: {op}")
        })
        .to_string());
    }
    let commands = commands_from_args(args)?;
    let cwd = resolve_cwd(args, workspace);
    let timeout_seconds = args
        .get("timeout_seconds")
        .and_then(Value::as_f64)
        .unwrap_or(policy.shell_timeout_seconds);
    let mut outputs = Vec::new();
    for command in commands {
        outputs.push(
            run_command(
                &command,
                &cwd,
                timeout_seconds,
                policy.shell_max_output_chars,
            )
            .await?,
        );
        if outputs
            .last()
            .and_then(|value| value.get("returncode"))
            .and_then(Value::as_i64)
            .unwrap_or(0)
            != 0
        {
            break;
        }
    }
    Ok(json!({
        "status": if outputs.iter().all(|item| item.get("returncode").and_then(Value::as_i64).unwrap_or(1) == 0) {
            "success"
        } else {
            "error"
        },
        "outputs": outputs,
        "cwd": cwd,
    })
    .to_string())
}

fn commands_from_args(args: &serde_json::Map<String, Value>) -> Result<Vec<String>> {
    if let Some(command) = args.get("command").and_then(Value::as_str) {
        return Ok(vec![command.to_string()]);
    }
    if let Some(commands) = args.get("commands").and_then(Value::as_array) {
        return commands
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(ToString::to_string)
                    .ok_or_else(|| anyhow!("shell commands must be strings"))
            })
            .collect();
    }
    Err(anyhow!("shell.run requires command or commands"))
}

fn resolve_cwd(args: &serde_json::Map<String, Value>, workspace: &Path) -> PathBuf {
    let raw = args.get("cwd").and_then(Value::as_str).unwrap_or("");
    if raw.is_empty() {
        return workspace.to_path_buf();
    }
    let path = PathBuf::from(raw);
    if path.is_absolute() {
        path
    } else {
        workspace.join(path)
    }
}

async fn run_command(
    command: &str,
    cwd: &Path,
    timeout_seconds: f64,
    max_output_chars: usize,
) -> Result<Value> {
    let mut child = Command::new("sh")
        .arg("-c")
        .arg(command)
        .current_dir(cwd)
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
    let status = match timeout(Duration::from_secs_f64(timeout_seconds), child.wait()).await {
        Ok(status) => status.context("failed to wait for shell command")?,
        Err(_) => {
            let _ = child.kill().await;
            return Ok(json!({
                "command": command,
                "status": "timeout",
                "returncode": null,
                "stdout": "",
                "stderr": format!("command timed out after {timeout_seconds}s"),
            }));
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
    Ok(json!({
        "command": command,
        "status": if status.success() { "success" } else { "error" },
        "returncode": status.code(),
        "stdout": truncate(String::from_utf8_lossy(&stdout).to_string(), max_output_chars),
        "stderr": truncate(String::from_utf8_lossy(&stderr).to_string(), max_output_chars),
    }))
}

fn truncate(mut value: String, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value;
    }
    value = value.chars().take(max_chars).collect();
    value.push_str("\n... truncated ...");
    value
}
