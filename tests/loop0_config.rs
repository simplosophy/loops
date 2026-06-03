use std::fs;
use std::sync::{Arc, Mutex};

use anyhow::Result;
use async_trait::async_trait;
use loops::loop0::config::Loop0RunConfig;
use loops::loop0::dotenv::read_dotenv;
use loops::loop0::io::InMemoryEventSink;
use loops::loop0::provider::{
    ProviderClient, ProviderOutput, ProviderRequest, ProviderResponse, ProviderStreamEvent,
};
use loops::loop0::runtime::{AgentRuntime, AgentSpec};
use loops::loop0::state::AgentState;
use loops::loop0::tool::registry_from_names;
use loops::loop0::types::{InteractionContext, UserInput};
use serde_json::json;

#[test]
fn loads_json_example_config_with_relative_paths() {
    let config = Loop0RunConfig::from_file("examples/loop0.config.json").unwrap();

    assert_eq!(config.agent.name, "loop0-cli-example");
    assert_eq!(config.agent.workspace, "..");
    assert_eq!(config.agent.tools, vec!["shell"]);
    assert_eq!(
        config.output.events_file.as_deref(),
        Some("../.loops-example-workspace/events.jsonl")
    );
    assert!(
        config
            .load_prompt_system()
            .unwrap()
            .contains("single loop0 agent runtime")
    );
    assert!(config.workspace_path().ends_with("examples/.."));
}

#[test]
fn reads_dotenv_key_values() {
    let dir = tempfile_dir();
    let path = dir.join(".env");
    fs::write(
        &path,
        "LOOPS_OPENAI_API_KEY='secret'\nexport LOOPS_DEEPSEEK_API_KEY=deepseek\n",
    )
    .unwrap();

    let env = read_dotenv(&path).unwrap();

    assert_eq!(env.get("LOOPS_OPENAI_API_KEY").unwrap(), "secret");
    assert_eq!(env.get("LOOPS_DEEPSEEK_API_KEY").unwrap(), "deepseek");
}

#[tokio::test]
async fn runtime_emits_stream_events_through_event_sink() {
    let mut config = Loop0RunConfig::default();
    config.provider.model = "fake-model".to_string();
    config.provider.api_key = "secret".to_string();
    config.run.input = Some("hello".to_string());
    config.run.stream = true;
    config.agent.tools.clear();
    config.prompt.system = "source={{ interaction.source }}".to_string();
    let runtime = AgentRuntime::new(AgentSpec {
        tools: registry_from_names(&config.agent.tools).unwrap(),
        state: AgentState::default(),
        config,
        provider: FakeProvider,
    });
    let mut sink = InMemoryEventSink::default();

    let result = runtime.run(&mut sink).await.unwrap();

    assert_eq!(result.output, "hello");
    assert_eq!(
        sink.events
            .iter()
            .filter(|event| event.r#type == "provider_delta")
            .map(|event| event.payload["text"].as_str().unwrap().to_string())
            .collect::<Vec<_>>(),
        vec!["hel", "lo"]
    );
    assert_eq!(
        sink.events
            .iter()
            .map(|event| event.r#type.as_str())
            .collect::<Vec<_>>(),
        vec![
            "run_started",
            "provider_started",
            "provider_delta",
            "provider_delta",
            "provider_finished"
        ]
    );
}

#[tokio::test]
async fn runtime_commits_history_between_runs() {
    let mut config = Loop0RunConfig::default();
    config.provider.model = "fake-model".to_string();
    config.provider.api_key = "secret".to_string();
    config.agent.tools.clear();
    config.prompt.system = "history={{ state.history | length }}".to_string();
    let provider = RecordingProvider::new(vec![provider_output("one"), provider_output("two")]);
    let requests = provider.requests.clone();
    let runtime = AgentRuntime::new(AgentSpec {
        tools: registry_from_names(&config.agent.tools).unwrap(),
        state: AgentState::default(),
        config,
        provider,
    });
    let mut sink = InMemoryEventSink::default();

    runtime
        .run_input(user_input("first", "thread-a"), &mut sink)
        .await
        .unwrap();
    runtime
        .run_input(user_input("second", "thread-a"), &mut sink)
        .await
        .unwrap();

    let requests = requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[1].messages[0].content, "history=2");
    assert_eq!(
        requests[1]
            .messages
            .iter()
            .map(|message| (message.role.as_str(), message.content.as_str()))
            .collect::<Vec<_>>(),
        vec![
            ("system", "history=2"),
            ("user", "first"),
            ("assistant", "one"),
            ("user", "second"),
        ]
    );
    let state = runtime.state_snapshot();
    let history = state.get_history("thread-a", None);
    assert_eq!(
        history
            .iter()
            .map(|message| (message.role.as_str(), message.content.as_str()))
            .collect::<Vec<_>>(),
        vec![
            ("user", "first"),
            ("assistant", "one"),
            ("user", "second"),
            ("assistant", "two"),
        ]
    );
}

struct FakeProvider;

#[async_trait]
impl ProviderClient for FakeProvider {
    async fn complete(&self, request: ProviderRequest) -> Result<ProviderOutput> {
        assert!(request.stream);
        assert_eq!(request.messages[0].content, "source=cli");
        Ok(ProviderOutput {
            response: ProviderResponse {
                content: "hello".to_string(),
                tool_calls: Vec::new(),
                stop_reason: Some("stop".to_string()),
                raw: json!({}),
            },
            events: vec![
                ProviderStreamEvent::TextDelta("hel".to_string()),
                ProviderStreamEvent::TextDelta("lo".to_string()),
            ],
        })
    }
}

struct RecordingProvider {
    requests: Arc<Mutex<Vec<ProviderRequest>>>,
    outputs: Arc<Mutex<Vec<ProviderOutput>>>,
}

impl RecordingProvider {
    fn new(outputs: Vec<ProviderOutput>) -> Self {
        Self {
            requests: Arc::new(Mutex::new(Vec::new())),
            outputs: Arc::new(Mutex::new(outputs)),
        }
    }
}

#[async_trait]
impl ProviderClient for RecordingProvider {
    async fn complete(&self, request: ProviderRequest) -> Result<ProviderOutput> {
        self.requests.lock().unwrap().push(request);
        Ok(self.outputs.lock().unwrap().remove(0))
    }
}

fn provider_output(content: &str) -> ProviderOutput {
    ProviderOutput {
        response: ProviderResponse {
            content: content.to_string(),
            tool_calls: Vec::new(),
            stop_reason: Some("stop".to_string()),
            raw: json!({}),
        },
        events: Vec::new(),
    }
}

fn user_input(text: &str, thread_id: &str) -> UserInput {
    UserInput::new(
        text,
        InteractionContext {
            thread_id: Some(thread_id.to_string()),
            ..InteractionContext::default()
        },
    )
}

fn tempfile_dir() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("loops-rust-test-{}", std::process::id()));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).unwrap();
    path
}
