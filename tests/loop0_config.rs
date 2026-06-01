use std::fs;

use loops::loop0::config::Loop0RunConfig;
use loops::loop0::dotenv::read_dotenv;

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

fn tempfile_dir() -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("loops-rust-test-{}", std::process::id()));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).unwrap();
    path
}
