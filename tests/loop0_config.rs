use std::fs;

use anyhow::Result;
use async_trait::async_trait;
use loops::loop0::config::Loop0RunConfig;
use loops::loop0::dotenv::read_dotenv;
use loops::loop0::io::InMemoryEventSink;
use loops::loop0::provider::{
    ProviderClient, ProviderOutput, ProviderRequest, ProviderResponse, ProviderStreamEvent,
};
use loops::loop0::runtime::{AgentRuntime, AgentSpec};
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

fn tempfile_dir() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("loops-rust-test-{}", std::process::id()));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).unwrap();
    path
}
