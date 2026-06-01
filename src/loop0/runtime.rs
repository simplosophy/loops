use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::{Context, Result, anyhow};
use minijinja::{Environment, context};
use serde_json::json;
use uuid::Uuid;

use crate::loop0::component::{Component, ComponentProfile, Contribution, RunContext};
use crate::loop0::config::Loop0RunConfig;
use crate::loop0::events::agent_event;
use crate::loop0::io::{EventSink, InMemoryEventSink};
use crate::loop0::provider::{
    OpenAiCompatibleProvider, ProviderClient, ProviderRequest, ProviderStreamEvent, ToolProfile,
};
use crate::loop0::state::AgentState;
use crate::loop0::tool::{ToolContext, ToolRegistry, registry_from_names};
use crate::loop0::types::{
    AgentEvent, AgentResult, InteractionContext, Message, RuntimeStats, UserInput,
};

pub struct AgentSpec<P> {
    pub config: Loop0RunConfig,
    pub provider: P,
    pub state: AgentState,
    pub tools: ToolRegistry,
    pub components: Vec<Arc<dyn Component>>,
}

pub struct AgentRuntime<P> {
    config: Loop0RunConfig,
    provider: P,
    state: Mutex<AgentState>,
    tools: ToolRegistry,
    components: Vec<Arc<dyn Component>>,
    components_setup: AtomicBool,
}

impl<P> AgentRuntime<P> {
    pub fn new(spec: AgentSpec<P>) -> Self {
        Self {
            config: spec.config,
            provider: spec.provider,
            state: Mutex::new(spec.state),
            tools: spec.tools,
            components: spec.components,
            components_setup: AtomicBool::new(false),
        }
    }

    pub fn state_snapshot(&self) -> AgentState {
        self.state
            .lock()
            .expect("agent state mutex poisoned")
            .clone()
    }

    pub async fn close(&self) -> Result<()> {
        for component in &self.components {
            component.teardown().await?;
        }
        Ok(())
    }
}

impl<P> AgentRuntime<P>
where
    P: ProviderClient,
{
    pub async fn run(&self, sink: &mut dyn EventSink) -> Result<AgentResult> {
        let input = self.input_from_config()?;
        self.run_input(input, sink).await
    }

    pub async fn run_input(
        &self,
        input: UserInput,
        sink: &mut dyn EventSink,
    ) -> Result<AgentResult> {
        self.ensure_components_setup().await?;
        let config = &self.config;
        let workspace = config.workspace_path();
        fs::create_dir_all(&workspace)
            .with_context(|| format!("failed to create workspace {}", workspace.display()))?;
        let run_id = format!("run_{}", Uuid::new_v4().simple());
        let input_text = input.text.clone();
        let interaction = input.interaction_context.clone();
        let thread_id = interaction
            .thread_id
            .clone()
            .or_else(|| interaction.session_id.clone())
            .unwrap_or_else(|| config.run.thread_id.clone());
        let history = self
            .state
            .lock()
            .expect("agent state mutex poisoned")
            .get_history(&thread_id, None);
        let run_context = RunContext {
            run_id: run_id.clone(),
            thread_id: thread_id.clone(),
            input: input.clone(),
            interaction: interaction.clone(),
            workspace: workspace.clone(),
            metadata: [("agent_name".to_string(), json!(config.agent.name.clone()))]
                .into_iter()
                .collect(),
        };
        let mut run_tools = self.tools.clone();
        let contributions = self
            .collect_contributions(&run_context, &mut run_tools)
            .await?;
        let prompt_blocks = contributions
            .iter()
            .flat_map(|contribution| contribution.prompt_blocks.iter().cloned())
            .collect::<Vec<_>>();
        let component_profiles = self
            .components
            .iter()
            .map(|component| component.profile())
            .collect::<Vec<_>>();
        let tool_profiles = run_tools.profiles();
        let system_prompt = render_prompt(
            &config.load_prompt_system()?,
            config,
            &input_text,
            &interaction,
            &history,
            &tool_profiles,
            &component_profiles,
            &prompt_blocks,
            &workspace,
            &run_id,
            &thread_id,
        )?;
        let user_prompt = render_prompt(
            &config.load_prompt_user()?,
            config,
            &input_text,
            &interaction,
            &history,
            &tool_profiles,
            &component_profiles,
            &prompt_blocks,
            &workspace,
            &run_id,
            &thread_id,
        )?;
        let mut stats = RuntimeStats::default();
        let mut events = Vec::new();
        let mut pending_state_messages = vec![Message::new("user", input_text.clone())];
        emit(
            &mut events,
            sink,
            &self.components,
            agent_event(
                "run_started",
                &run_id,
                json!({
                    "thread_id": thread_id,
                    "interaction": interaction.source,
                    "input_chars": input_text.chars().count(),
                }),
            ),
        )
        .await?;
        let mut messages = vec![Message::new("system", system_prompt)];
        messages.extend(history);
        messages.push(Message::new("user", user_prompt));
        for turn in 1..=config.policy.max_turns {
            stats.turns += 1;
            emit(
                &mut events,
                sink,
                &self.components,
                agent_event(
                    "provider_started",
                    &run_id,
                    json!({
                        "turn": turn,
                        "provider": config.provider.name,
                        "model": config.provider.model,
                        "stream": config.run.stream,
                        "tool_count": tool_profiles.len(),
                    }),
                ),
            )
            .await?;
            let output = self
                .provider
                .complete(ProviderRequest {
                    messages: messages.clone(),
                    tools: tool_profiles.clone(),
                    stream: config.run.stream,
                    parallel_tool_calls: config.policy.parallel_tool_calls,
                })
                .await?;
            for stream_event in output.events {
                match stream_event {
                    ProviderStreamEvent::TextDelta(text) => {
                        emit(
                            &mut events,
                            sink,
                            &self.components,
                            agent_event("provider_delta", &run_id, json!({"text": text})),
                        )
                        .await?
                    }
                    ProviderStreamEvent::ReasoningDelta(text) => {
                        emit(
                            &mut events,
                            sink,
                            &self.components,
                            agent_event("provider_reasoning_delta", &run_id, json!({"text": text})),
                        )
                        .await?
                    }
                }
            }
            let response = output.response;
            emit(
                &mut events,
                sink,
                &self.components,
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
            )
            .await?;
            if response.tool_calls.is_empty() {
                pending_state_messages.push(Message::new("assistant", response.content.clone()));
                let result = AgentResult {
                    output: response.content,
                    run_id,
                    thread_id: thread_id.clone(),
                    stop_reason: "completed".to_string(),
                    stats,
                    events,
                };
                self.commit_messages(&thread_id, pending_state_messages);
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
                    &self.components,
                    agent_event(
                        "tool_started",
                        &run_id,
                        json!({
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                        }),
                    ),
                )
                .await?;
                let mut ctx = ToolContext {
                    agent_id: self
                        .state
                        .lock()
                        .expect("agent state mutex poisoned")
                        .agent_id
                        .clone(),
                    run_id: run_id.clone(),
                    workspace: workspace.clone(),
                    policy: &config.policy,
                    metadata: [("thread_id".to_string(), json!(thread_id.clone()))]
                        .into_iter()
                        .collect(),
                    emitted_events: Vec::new(),
                };
                let tool_result = run_tools
                    .execute(&tool_call.name, &mut ctx, &tool_call.arguments)
                    .await?;
                let content = tool_result.message_content();
                emit(
                    &mut events,
                    sink,
                    &self.components,
                    agent_event(
                        "tool_finished",
                        &run_id,
                        json!({
                            "tool_name": tool_call.name,
                            "tool_call_id": tool_call.id,
                            "status": tool_result.status,
                            "output": tool_result.output,
                            "error": tool_result.error,
                            "metadata": tool_result.metadata,
                            "content_chars": content.chars().count(),
                        }),
                    ),
                )
                .await?;
                messages.push(Message::tool(content, tool_call.id));
                for event in ctx.emitted_events {
                    emit(&mut events, sink, &self.components, event).await?;
                }
                if !tool_result.is_success() && !config.policy.allow_tool_errors {
                    return Err(anyhow!("tool execution failed"));
                }
            }
        }
        let result = AgentResult {
            output: String::new(),
            run_id,
            thread_id: thread_id.clone(),
            stop_reason: "turn_limit_reached".to_string(),
            stats,
            events,
        };
        self.commit_messages(&thread_id, pending_state_messages);
        write_events(config, &result.events)?;
        Ok(result)
    }

    async fn ensure_components_setup(&self) -> Result<()> {
        if self.components_setup.load(Ordering::Acquire) {
            return Ok(());
        }
        for component in &self.components {
            component.setup().await?;
        }
        self.components_setup.store(true, Ordering::Release);
        Ok(())
    }

    async fn collect_contributions(
        &self,
        run_context: &RunContext,
        run_tools: &mut ToolRegistry,
    ) -> Result<Vec<Contribution>> {
        let mut contributions = Vec::new();
        for component in &self.components {
            let contribution = component.contribute(run_context).await?;
            run_tools.extend_arc(contribution.tools.iter().cloned())?;
            contributions.push(contribution);
        }
        Ok(contributions)
    }

    fn input_from_config(&self) -> Result<UserInput> {
        let config = &self.config;
        let text = config.load_input()?;
        Ok(UserInput::new(
            text,
            InteractionContext {
                source: config.interaction.source.clone(),
                session_id: config.interaction.session_id.clone(),
                thread_id: Some(config.run.thread_id.clone()),
                actor_id: config.interaction.actor_id.clone(),
                reply_to: config.interaction.reply_to.clone(),
                audience: config.interaction.audience.clone(),
                interactive: config.interaction.interactive,
                stream: config.run.stream,
                locale: config.interaction.locale.clone(),
                raw: config.interaction.raw.clone(),
            },
        ))
    }

    fn commit_messages(&self, thread_id: &str, messages: Vec<Message>) {
        let mut state = self.state.lock().expect("agent state mutex poisoned");
        for message in messages {
            state.append_message(thread_id, message);
        }
    }
}

pub async fn run_loop0(config: &Loop0RunConfig) -> Result<AgentResult> {
    let provider = OpenAiCompatibleProvider::new(config.provider.clone())?;
    let runtime = AgentRuntime::new(AgentSpec {
        config: config.clone(),
        provider,
        state: AgentState::default(),
        tools: registry_from_names(&config.agent.tools)?,
        components: Vec::new(),
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

async fn emit(
    events: &mut Vec<AgentEvent>,
    sink: &mut dyn EventSink,
    components: &[Arc<dyn Component>],
    event: AgentEvent,
) -> Result<()> {
    events.push(event.clone());
    sink.send(&event)?;
    for component in components {
        component.handle_event(&event).await?;
    }
    Ok(())
}

fn render_prompt(
    template: &str,
    config: &Loop0RunConfig,
    input_text: &str,
    interaction: &InteractionContext,
    history: &[Message],
    tools: &[ToolProfile],
    component_profiles: &[ComponentProfile],
    component_prompt_blocks: &[String],
    workspace: &Path,
    run_id: &str,
    thread_id: &str,
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
                "source": interaction.source,
                "session_id": interaction.session_id,
                "thread_id": interaction.thread_id,
                "actor_id": interaction.actor_id,
                "reply_to": interaction.reply_to,
                "audience": interaction.audience,
                "interactive": interaction.interactive,
                "stream": interaction.stream,
                "locale": interaction.locale,
                "raw": interaction.raw,
            }),
            input => json!({
                "text": input_text,
            }),
            run => json!({
                "run_id": run_id,
                "thread_id": thread_id,
            }),
            state => json!({
                "history": history,
            }),
            tools => tools,
            components => json!({
                "profiles": component_profiles,
                "prompt_blocks": component_prompt_blocks,
            }),
        },
    )
    .context("failed to render prompt")
}
