use std::fs;
use std::path::Path;

use anyhow::{Context, Result, anyhow};
use minijinja::{Environment, context};
use serde_json::json;
use uuid::Uuid;

use crate::loop0::config::Loop0RunConfig;
use crate::loop0::events::agent_event;
use crate::loop0::io::{EventSink, InMemoryEventSink};
use crate::loop0::provider::{
    OpenAiCompatibleProvider, ProviderClient, ProviderRequest, ProviderStreamEvent, ToolProfile,
};
use crate::loop0::shell::{execute_shell_tool, shell_tool_profile};
use crate::loop0::types::{AgentEvent, AgentResult, Message, RuntimeStats};

pub struct AgentSpec<P> {
    pub config: Loop0RunConfig,
    pub provider: P,
}

pub struct AgentRuntime<P> {
    spec: AgentSpec<P>,
}

impl<P> AgentRuntime<P> {
    pub fn new(spec: AgentSpec<P>) -> Self {
        Self { spec }
    }
}

impl<P> AgentRuntime<P>
where
    P: ProviderClient,
{
    pub async fn run(&self, sink: &mut dyn EventSink) -> Result<AgentResult> {
        let config = &self.spec.config;
        let workspace = config.workspace_path();
        fs::create_dir_all(&workspace)
            .with_context(|| format!("failed to create workspace {}", workspace.display()))?;
        let input = config.load_input()?;
        let system_prompt =
            render_prompt(&config.load_prompt_system()?, config, &input, &workspace)?;
        let user_prompt = render_prompt(&config.load_prompt_user()?, config, &input, &workspace)?;
        let run_id = format!("run_{}", Uuid::new_v4().simple());
        let mut stats = RuntimeStats::default();
        let mut events = Vec::new();
        emit(
            &mut events,
            sink,
            agent_event(
                "run_started",
                &run_id,
                json!({
                    "thread_id": config.run.thread_id,
                    "interaction": config.interaction.source,
                    "input_chars": input.chars().count(),
                }),
            ),
        )?;
        let mut messages = vec![
            Message::new("system", system_prompt),
            Message::new("user", user_prompt),
        ];
        let tools = build_tools(&config.agent.tools)?;
        for turn in 1..=config.policy.max_turns {
            stats.turns += 1;
            emit(
                &mut events,
                sink,
                agent_event(
                    "provider_started",
                    &run_id,
                    json!({
                        "turn": turn,
                        "provider": config.provider.name,
                        "model": config.provider.model,
                        "stream": config.run.stream,
                        "tool_count": tools.len(),
                    }),
                ),
            )?;
            let output = self
                .spec
                .provider
                .complete(ProviderRequest {
                    messages: messages.clone(),
                    tools: tools.clone(),
                    stream: config.run.stream,
                    parallel_tool_calls: config.policy.parallel_tool_calls,
                })
                .await?;
            for stream_event in output.events {
                match stream_event {
                    ProviderStreamEvent::TextDelta(text) => emit(
                        &mut events,
                        sink,
                        agent_event("provider_delta", &run_id, json!({"text": text})),
                    )?,
                    ProviderStreamEvent::ReasoningDelta(text) => emit(
                        &mut events,
                        sink,
                        agent_event("provider_reasoning_delta", &run_id, json!({"text": text})),
                    )?,
                }
            }
            let response = output.response;
            emit(
                &mut events,
                sink,
                agent_event(
                    "provider_finished",
                    &run_id,
                    json!({
                        "turn": turn,
                        "tool_call_count": response.tool_calls.len(),
                        "content_chars": response.content.chars().count(),
                        "stop_reason": response.stop_reason,
                    }),
                ),
            )?;
            if response.tool_calls.is_empty() {
                let result = AgentResult {
                    output: response.content,
                    run_id,
                    thread_id: config.run.thread_id.clone(),
                    stop_reason: "completed".to_string(),
                    stats,
                    events,
                };
                write_events(config, &result.events)?;
                return Ok(result);
            }
            let mut assistant = Message::new("assistant", response.content);
            assistant.tool_calls = response.tool_calls.clone();
            messages.push(assistant);
            for tool_call in response.tool_calls {
                stats.tool_calls += 1;
                emit(
                    &mut events,
                    sink,
                    agent_event(
                        "tool_started",
                        &run_id,
                        json!({
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                        }),
                    ),
                )?;
                let content = match tool_call.name.as_str() {
                    "shell" => execute_shell_tool(&tool_call, &workspace, &config.policy).await?,
                    other => json!({
                        "status": "not_found",
                        "error": format!("unknown tool: {other}")
                    })
                    .to_string(),
                };
                emit(
                    &mut events,
                    sink,
                    agent_event(
                        "tool_finished",
                        &run_id,
                        json!({
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                            "content_chars": content.chars().count(),
                        }),
                    ),
                )?;
                messages.push(Message::tool(content, tool_call.id));
            }
        }
        let result = AgentResult {
            output: String::new(),
            run_id,
            thread_id: config.run.thread_id.clone(),
            stop_reason: "turn_limit_reached".to_string(),
            stats,
            events,
        };
        write_events(config, &result.events)?;
        Ok(result)
    }
}

pub async fn run_loop0(config: &Loop0RunConfig) -> Result<AgentResult> {
    let provider = OpenAiCompatibleProvider::new(config.provider.clone())?;
    let runtime = AgentRuntime::new(AgentSpec {
        config: config.clone(),
        provider,
    });
    let mut sink = InMemoryEventSink::default();
    runtime.run(&mut sink).await
}

pub fn write_events(config: &Loop0RunConfig, events: &[AgentEvent]) -> Result<()> {
    let Some(path) = config.events_path() else {
        return Ok(());
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create events directory {}", parent.display()))?;
    }
    let lines = events
        .iter()
        .map(serde_json::to_string)
        .collect::<std::result::Result<Vec<_>, _>>()
        .context("failed to serialize events")?
        .join("\n");
    fs::write(&path, format!("{lines}\n"))
        .with_context(|| format!("failed to write events file {}", path.display()))
}

fn build_tools(names: &[String]) -> Result<Vec<ToolProfile>> {
    names
        .iter()
        .map(|name| match name.as_str() {
            "shell" => Ok(shell_tool_profile()),
            other => Err(anyhow!("unsupported tool: {other}")),
        })
        .collect()
}

fn emit(events: &mut Vec<AgentEvent>, sink: &mut dyn EventSink, event: AgentEvent) -> Result<()> {
    sink.send(&event)?;
    events.push(event);
    Ok(())
}

fn render_prompt(
    template: &str,
    config: &Loop0RunConfig,
    input_text: &str,
    workspace: &Path,
) -> Result<String> {
    let env = Environment::new();
    env.render_str(
        template,
        context! {
            agent => json!({
                "name": config.agent.name,
                "description": config.agent.description,
                "metadata": config.agent.metadata,
                "workspace": workspace.display().to_string(),
            }),
            provider => json!({
                "name": config.provider.name,
                "model": config.provider.model,
                "base_url": config.provider.base_url,
            }),
            interaction => json!({
                "source": config.interaction.source,
                "session_id": config.interaction.session_id,
                "thread_id": config.run.thread_id,
                "actor_id": config.interaction.actor_id,
                "reply_to": config.interaction.reply_to,
                "audience": config.interaction.audience,
                "interactive": config.interaction.interactive,
                "stream": config.run.stream,
                "locale": config.interaction.locale,
                "raw": config.interaction.raw,
            }),
            input => json!({
                "text": input_text,
            }),
            run => json!({
                "thread_id": config.run.thread_id,
            }),
            tools => build_tools(&config.agent.tools)?,
        },
    )
    .context("failed to render prompt")
}
