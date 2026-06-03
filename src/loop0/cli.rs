use std::collections::BTreeMap;
use std::io::{self, Read};

use anyhow::{Context, Result, anyhow};
use clap::Parser;

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
    model: Option<String>,
    #[arg(long)]
    api_key: Option<String>,
    #[arg(long)]
    api_key_env: Option<String>,
    #[arg(long)]
    base_url: Option<String>,
    #[arg(long)]
    input: Option<String>,
    #[arg(long)]
    input_file: Option<String>,
    #[arg(long)]
    thread_id: Option<String>,
    #[arg(long)]
    stream: bool,
    #[arg(long)]
    no_tools: bool,
    #[arg(long)]
    output: Option<String>,
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
    apply_overrides(&mut config, &args);
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

fn apply_overrides(config: &mut Loop0RunConfig, args: &Args) {
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
    if args.no_tools {
        config.agent.tools.clear();
    }
    if let Some(output) = &args.output {
        config.output.format = output.clone();
    }
    if let Some(events_file) = &args.events_file {
        config.output.events_file = Some(events_file.clone());
    }
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

fn atty_stdin() -> bool {
    use std::io::IsTerminal;
    io::stdin().is_terminal()
}
