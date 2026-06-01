use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Read};

use anyhow::{Context, Result, anyhow};
use clap::Parser;
use serde_json::Value;

use crate::loop0::config::{Loop0RunConfig, ProviderConfig};
use crate::loop0::dotenv::load_env;
use crate::loop0::runtime::run_loop0;

#[derive(Debug, Parser)]
#[command(name = "loops-loop0", about = "Run one loop0 Agent turn.")]
pub struct Args {
    #[arg()]
    message: Vec<String>,
    #[arg(long)]
    config: Option<String>,
    #[arg(long)]
    env_file: Option<String>,
    #[arg(long)]
    system: Option<String>,
    #[arg(long)]
    system_file: Option<String>,
    #[arg(long)]
    user: Option<String>,
    #[arg(long)]
    user_file: Option<String>,
    #[arg(long)]
    prompt_engine: Option<String>,
    #[arg(long = "provider")]
    provider_kind: Option<String>,
    #[arg(long)]
    provider_name: Option<String>,
    #[arg(long)]
    model: Option<String>,
    #[arg(long)]
    api_key: Option<String>,
    #[arg(long)]
    api_key_env: Option<String>,
    #[arg(long)]
    base_url: Option<String>,
    #[arg(long)]
    timeout_seconds: Option<f64>,
    #[arg(long)]
    disable_verify_ssl: bool,
    #[arg(long)]
    verify_ssl: bool,
    #[arg(long = "header")]
    headers: Vec<String>,
    #[arg(long)]
    reasoning_effort: Option<String>,
    #[arg(long)]
    extra_body: Option<String>,
    #[arg(long)]
    extra_body_file: Option<String>,
    #[arg(long)]
    agent_name: Option<String>,
    #[arg(long)]
    agent_description: Option<String>,
    #[arg(long)]
    workspace: Option<String>,
    #[arg(long = "metadata")]
    metadata: Vec<String>,
    #[arg(long = "tool")]
    tools: Vec<String>,
    #[arg(long)]
    input: Option<String>,
    #[arg(long)]
    input_file: Option<String>,
    #[arg(long)]
    thread_id: Option<String>,
    #[arg(long)]
    stream: bool,
    #[arg(long)]
    log_level: Option<String>,
    #[arg(long)]
    no_tools: bool,
    #[arg(long)]
    max_turns: Option<usize>,
    #[arg(long)]
    allow_tool_errors: bool,
    #[arg(long)]
    no_allow_tool_errors: bool,
    #[arg(long)]
    parallel_tool_calls: bool,
    #[arg(long)]
    no_parallel_tool_calls: bool,
    #[arg(long)]
    max_parallel_tool_calls: Option<usize>,
    #[arg(long)]
    auto_approve: bool,
    #[arg(long)]
    no_auto_approve: bool,
    #[arg(long)]
    shell_timeout_seconds: Option<f64>,
    #[arg(long)]
    shell_max_output_chars: Option<usize>,
    #[arg(long)]
    shell_require_approval_for_background: bool,
    #[arg(long)]
    no_shell_require_approval_for_background: bool,
    #[arg(long)]
    shell_external_path_policy: Option<String>,
    #[arg(long)]
    source: Option<String>,
    #[arg(long)]
    session_id: Option<String>,
    #[arg(long)]
    actor_id: Option<String>,
    #[arg(long)]
    reply_to: Option<String>,
    #[arg(long)]
    audience: Option<String>,
    #[arg(long)]
    interactive: bool,
    #[arg(long)]
    no_interactive: bool,
    #[arg(long)]
    locale: Option<String>,
    #[arg(long = "interaction-raw")]
    interaction_raw: Vec<String>,
    #[arg(long)]
    output: Option<String>,
    #[arg(long)]
    show_events: bool,
    #[arg(long)]
    no_show_events: bool,
    #[arg(long)]
    events_file: Option<String>,
}

pub async fn main() -> i32 {
    match run_from_args(Args::parse()).await {
        Ok(()) => 0,
        Err(error) => {
            eprintln!("loops-loop0 failed: {error:#}");
            1
        }
    }
}

async fn run_from_args(args: Args) -> Result<()> {
    let mut config = if let Some(path) = &args.config {
        Loop0RunConfig::from_file(path)?
    } else {
        Loop0RunConfig::default()
    };
    apply_overrides(&mut config, &args)?;
    apply_env(&mut config)?;
    if config.run.input.is_none() && config.run.input_file.is_none() && args.message.is_empty() {
        let mut buffer = String::new();
        if !atty_stdin() {
            io::stdin()
                .read_to_string(&mut buffer)
                .context("failed to read stdin")?;
            if !buffer.is_empty() {
                config.run.input = Some(buffer);
            }
        }
    }
    let result = run_loop0(&config).await?;
    if config.output.format == "json" {
        println!("{}", serde_json::to_string(&result)?);
    } else if !result.output.is_empty() {
        println!("{}", result.output);
    }
    if config.output.show_events {
        for event in result.events {
            eprintln!("{}", event.r#type);
        }
    }
    Ok(())
}

fn apply_overrides(config: &mut Loop0RunConfig, args: &Args) -> Result<()> {
    if let Some(path) = &args.env_file {
        config.env_file = Some(path.clone());
    }
    if let Some(system) = &args.system {
        config.prompt.system = system.clone();
        config.prompt.system_file = None;
    }
    if let Some(path) = &args.system_file {
        config.prompt.system_file = Some(path.clone());
    }
    if let Some(user) = &args.user {
        config.prompt.user = user.clone();
        config.prompt.user_file = None;
    }
    if let Some(path) = &args.user_file {
        config.prompt.user_file = Some(path.clone());
    }
    if let Some(engine) = &args.prompt_engine {
        config.prompt.engine = engine.clone();
    }
    if let Some(kind) = &args.provider_kind {
        config.provider.kind = kind.clone();
    }
    if let Some(name) = &args.provider_name {
        config.provider.name = name.clone();
    }
    if let Some(model) = &args.model {
        config.provider.model = model.clone();
    }
    if let Some(api_key) = &args.api_key {
        config.provider.api_key = api_key.clone();
    }
    if let Some(api_key_env) = &args.api_key_env {
        config.provider.api_key_env = api_key_env.clone();
    }
    if let Some(base_url) = &args.base_url {
        config.provider.base_url = base_url.clone();
    }
    if let Some(timeout) = args.timeout_seconds {
        config.provider.timeout_seconds = timeout;
    }
    if args.disable_verify_ssl {
        config.provider.disable_verify_ssl = true;
    }
    if args.verify_ssl {
        config.provider.disable_verify_ssl = false;
    }
    if !args.headers.is_empty() {
        config
            .provider
            .headers
            .extend(parse_key_values(&args.headers)?);
    }
    if let Some(reasoning_effort) = &args.reasoning_effort {
        config.provider.reasoning_effort = Some(reasoning_effort.clone());
    }
    if let Some(extra_body) = &args.extra_body {
        config
            .provider
            .extra_body
            .extend(parse_json_object(extra_body)?);
    }
    if let Some(path) = &args.extra_body_file {
        let text = fs::read_to_string(path).with_context(|| format!("failed to read {path}"))?;
        config.provider.extra_body.extend(parse_json_object(&text)?);
    }
    if let Some(name) = &args.agent_name {
        config.agent.name = name.clone();
    }
    if let Some(description) = &args.agent_description {
        config.agent.description = description.clone();
    }
    if let Some(workspace) = &args.workspace {
        config.agent.workspace = workspace.clone();
    }
    if !args.metadata.is_empty() {
        config.agent.metadata.extend(
            parse_key_values(&args.metadata)?
                .into_iter()
                .map(|(key, value)| (key, Value::String(value))),
        );
    }
    if let Some(input) = &args.input {
        config.run.input = Some(input.clone());
        config.run.input_file = None;
    }
    if let Some(input_file) = &args.input_file {
        config.run.input_file = Some(input_file.clone());
    }
    if !args.message.is_empty() {
        config.run.input = Some(args.message.join(" "));
        config.run.input_file = None;
    }
    if let Some(thread_id) = &args.thread_id {
        config.run.thread_id = thread_id.clone();
    }
    if args.stream {
        config.run.stream = true;
    }
    if let Some(log_level) = &args.log_level {
        config.run.log_level = log_level.clone();
    }
    if args.no_tools {
        config.agent.tools.clear();
    } else if !args.tools.is_empty() {
        config.agent.tools = args.tools.clone();
    }
    if let Some(max_turns) = args.max_turns {
        config.policy.max_turns = max_turns;
    }
    if args.allow_tool_errors {
        config.policy.allow_tool_errors = true;
    }
    if args.no_allow_tool_errors {
        config.policy.allow_tool_errors = false;
    }
    if args.parallel_tool_calls {
        config.policy.parallel_tool_calls = Some(true);
    }
    if args.no_parallel_tool_calls {
        config.policy.parallel_tool_calls = Some(false);
    }
    if let Some(max_parallel_tool_calls) = args.max_parallel_tool_calls {
        config.policy.max_parallel_tool_calls = Some(max_parallel_tool_calls);
    }
    if args.auto_approve {
        config.policy.auto_approve = true;
    }
    if args.no_auto_approve {
        config.policy.auto_approve = false;
    }
    if let Some(shell_timeout_seconds) = args.shell_timeout_seconds {
        config.policy.shell_timeout_seconds = shell_timeout_seconds;
    }
    if let Some(shell_max_output_chars) = args.shell_max_output_chars {
        config.policy.shell_max_output_chars = shell_max_output_chars;
    }
    if args.shell_require_approval_for_background {
        config.policy.shell_require_approval_for_background = true;
    }
    if args.no_shell_require_approval_for_background {
        config.policy.shell_require_approval_for_background = false;
    }
    if let Some(policy) = &args.shell_external_path_policy {
        config.policy.shell_external_path_policy = policy.clone();
    }
    if let Some(source) = &args.source {
        config.interaction.source = source.clone();
    }
    if let Some(session_id) = &args.session_id {
        config.interaction.session_id = Some(session_id.clone());
    }
    if let Some(actor_id) = &args.actor_id {
        config.interaction.actor_id = Some(actor_id.clone());
    }
    if let Some(reply_to) = &args.reply_to {
        config.interaction.reply_to = Some(reply_to.clone());
    }
    if let Some(audience) = &args.audience {
        config.interaction.audience = audience.clone();
    }
    if args.interactive {
        config.interaction.interactive = true;
    }
    if args.no_interactive {
        config.interaction.interactive = false;
    }
    if let Some(locale) = &args.locale {
        config.interaction.locale = Some(locale.clone());
    }
    if !args.interaction_raw.is_empty() {
        config.interaction.raw.extend(
            parse_key_values(&args.interaction_raw)?
                .into_iter()
                .map(|(key, value)| (key, Value::String(value))),
        );
    }
    if let Some(output) = &args.output {
        config.output.format = output.clone();
    }
    if args.show_events {
        config.output.show_events = true;
    }
    if args.no_show_events {
        config.output.show_events = false;
    }
    if let Some(events_file) = &args.events_file {
        config.output.events_file = Some(events_file.clone());
    }
    Ok(())
}

fn apply_env(config: &mut Loop0RunConfig) -> Result<()> {
    let env = load_env(config)?;
    if config.provider.api_key.is_empty() {
        config.provider.api_key = env
            .get(&config.provider.api_key_env)
            .cloned()
            .unwrap_or_default();
    }
    validate_provider(&config.provider, &env)
}

fn validate_provider(config: &ProviderConfig, _env: &BTreeMap<String, String>) -> Result<()> {
    if config.api_key.is_empty() {
        return Err(anyhow!(
            "missing provider API key; pass --api-key or set {}",
            config.api_key_env
        ));
    }
    if config.model.is_empty() {
        return Err(anyhow!(
            "missing provider model; pass --model or set provider.model"
        ));
    }
    Ok(())
}

fn parse_key_values(values: &[String]) -> Result<BTreeMap<String, String>> {
    let mut parsed = BTreeMap::new();
    for value in values {
        let Some((key, item)) = value.split_once('=') else {
            return Err(anyhow!("expected KEY=VALUE, got: {value}"));
        };
        if key.is_empty() {
            return Err(anyhow!("expected non-empty KEY in: {value}"));
        }
        parsed.insert(key.to_string(), item.to_string());
    }
    Ok(parsed)
}

fn parse_json_object(text: &str) -> Result<BTreeMap<String, Value>> {
    let value: Value = serde_json::from_str(text).context("failed to parse JSON object")?;
    let Some(object) = value.as_object() else {
        return Err(anyhow!("expected a JSON object"));
    };
    Ok(object
        .iter()
        .map(|(key, value)| (key.clone(), value.clone()))
        .collect())
}

fn atty_stdin() -> bool {
    use std::io::IsTerminal;
    io::stdin().is_terminal()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_flags_override_full_loop0_config() {
        let mut config = Loop0RunConfig::default();
        let args = Args::parse_from([
            "loops-loop0",
            "--system",
            "system",
            "--user",
            "{{ input.text }}!",
            "--prompt-engine",
            "jinja",
            "--provider",
            "openai-compatible",
            "--provider-name",
            "deepseek",
            "--model",
            "deepseek-chat",
            "--api-key-env",
            "TEST_KEY",
            "--base-url",
            "https://api.deepseek.com",
            "--timeout-seconds",
            "12",
            "--disable-verify-ssl",
            "--header",
            "X-Test=1",
            "--reasoning-effort",
            "low",
            "--extra-body",
            "{\"temperature\":0.2}",
            "--agent-name",
            "cli-agent",
            "--agent-description",
            "CLI agent",
            "--workspace",
            "workspace",
            "--metadata",
            "team=loop0",
            "--tool",
            "shell",
            "--max-turns",
            "3",
            "--no-allow-tool-errors",
            "--parallel-tool-calls",
            "--max-parallel-tool-calls",
            "2",
            "--auto-approve",
            "--shell-timeout-seconds",
            "5",
            "--shell-max-output-chars",
            "100",
            "--no-shell-require-approval-for-background",
            "--shell-external-path-policy",
            "deny",
            "--input",
            "hello",
            "--thread-id",
            "thread-cli",
            "--stream",
            "--log-level",
            "INFO",
            "--source",
            "terminal",
            "--session-id",
            "session-cli",
            "--actor-id",
            "actor-cli",
            "--reply-to",
            "msg-cli",
            "--audience",
            "user",
            "--interactive",
            "--locale",
            "zh-CN",
            "--interaction-raw",
            "raw_key=raw_value",
            "--output",
            "json",
            "--show-events",
            "--events-file",
            "events.jsonl",
        ]);

        apply_overrides(&mut config, &args).unwrap();

        assert_eq!(config.prompt.system, "system");
        assert_eq!(config.prompt.user, "{{ input.text }}!");
        assert_eq!(config.provider.kind, "openai-compatible");
        assert_eq!(config.provider.name, "deepseek");
        assert_eq!(config.provider.model, "deepseek-chat");
        assert_eq!(config.provider.api_key_env, "TEST_KEY");
        assert_eq!(config.provider.base_url, "https://api.deepseek.com");
        assert_eq!(config.provider.timeout_seconds, 12.0);
        assert!(config.provider.disable_verify_ssl);
        assert_eq!(config.provider.headers["X-Test"], "1");
        assert_eq!(config.provider.reasoning_effort.as_deref(), Some("low"));
        assert_eq!(config.provider.extra_body["temperature"], 0.2);
        assert_eq!(config.agent.name, "cli-agent");
        assert_eq!(config.agent.description, "CLI agent");
        assert_eq!(config.agent.workspace, "workspace");
        assert_eq!(config.agent.metadata["team"], "loop0");
        assert_eq!(config.agent.tools, vec!["shell"]);
        assert_eq!(config.policy.max_turns, 3);
        assert!(!config.policy.allow_tool_errors);
        assert_eq!(config.policy.parallel_tool_calls, Some(true));
        assert_eq!(config.policy.max_parallel_tool_calls, Some(2));
        assert!(config.policy.auto_approve);
        assert_eq!(config.policy.shell_timeout_seconds, 5.0);
        assert_eq!(config.policy.shell_max_output_chars, 100);
        assert!(!config.policy.shell_require_approval_for_background);
        assert_eq!(config.policy.shell_external_path_policy, "deny");
        assert_eq!(config.run.input.as_deref(), Some("hello"));
        assert_eq!(config.run.thread_id, "thread-cli");
        assert!(config.run.stream);
        assert_eq!(config.run.log_level, "INFO");
        assert_eq!(config.interaction.source, "terminal");
        assert_eq!(
            config.interaction.session_id.as_deref(),
            Some("session-cli")
        );
        assert_eq!(config.interaction.actor_id.as_deref(), Some("actor-cli"));
        assert_eq!(config.interaction.reply_to.as_deref(), Some("msg-cli"));
        assert!(config.interaction.interactive);
        assert_eq!(config.interaction.locale.as_deref(), Some("zh-CN"));
        assert_eq!(config.interaction.raw["raw_key"], "raw_value");
        assert_eq!(config.output.format, "json");
        assert!(config.output.show_events);
        assert_eq!(config.output.events_file.as_deref(), Some("events.jsonl"));
    }

    #[test]
    fn cli_message_overrides_config_input() {
        let mut config = Loop0RunConfig::default();
        config.run.input = Some("from config".to_string());
        let args = Args::parse_from(["loops-loop0", "hello", "world"]);

        apply_overrides(&mut config, &args).unwrap();

        assert_eq!(config.run.input.as_deref(), Some("hello world"));
        assert!(config.run.input_file.is_none());
    }
}
