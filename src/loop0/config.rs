use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const DEFAULT_SYSTEM_PROMPT: &str = "You are a helpful agent.";
pub const DEFAULT_API_KEY_ENV: &str = "LOOPS_OPENAI_API_KEY";
pub const DEFAULT_BASE_URL: &str = "https://api.openai.com/v1";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct PromptConfig {
    pub system: String,
    pub system_file: Option<String>,
    pub user: String,
    pub user_file: Option<String>,
    pub engine: String,
}

impl Default for PromptConfig {
    fn default() -> Self {
        Self {
            system: DEFAULT_SYSTEM_PROMPT.to_string(),
            system_file: None,
            user: "{{ input.text }}".to_string(),
            user_file: None,
            engine: "jinja".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ProviderConfig {
    #[serde(rename = "type")]
    pub kind: String,
    pub name: String,
    pub model: String,
    pub api_key: String,
    pub api_key_env: String,
    pub base_url: String,
    pub timeout_seconds: f64,
    pub disable_verify_ssl: bool,
    pub headers: BTreeMap<String, String>,
    pub reasoning_effort: Option<String>,
    pub extra_body: BTreeMap<String, Value>,
}

impl Default for ProviderConfig {
    fn default() -> Self {
        Self {
            kind: "openai-compatible".to_string(),
            name: "openai-compatible".to_string(),
            model: String::new(),
            api_key: String::new(),
            api_key_env: DEFAULT_API_KEY_ENV.to_string(),
            base_url: DEFAULT_BASE_URL.to_string(),
            timeout_seconds: 60.0,
            disable_verify_ssl: false,
            headers: BTreeMap::new(),
            reasoning_effort: None,
            extra_body: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct PolicyConfig {
    pub max_turns: usize,
    pub allow_tool_errors: bool,
    pub parallel_tool_calls: Option<bool>,
    pub max_parallel_tool_calls: Option<usize>,
    pub auto_approve: bool,
    pub shell_timeout_seconds: f64,
    pub shell_max_output_chars: usize,
    pub shell_require_approval_for_background: bool,
    pub shell_external_path_policy: String,
}

impl Default for PolicyConfig {
    fn default() -> Self {
        Self {
            max_turns: 20,
            allow_tool_errors: true,
            parallel_tool_calls: None,
            max_parallel_tool_calls: Some(1),
            auto_approve: false,
            shell_timeout_seconds: 60.0,
            shell_max_output_chars: 30_000,
            shell_require_approval_for_background: true,
            shell_external_path_policy: "ask".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AgentConfig {
    pub name: String,
    pub description: String,
    pub workspace: String,
    pub metadata: BTreeMap<String, Value>,
    pub tools: Vec<String>,
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            name: "loop0-cli".to_string(),
            description: String::new(),
            workspace: ".loops-workspace".to_string(),
            metadata: BTreeMap::new(),
            tools: vec!["shell".to_string()],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct RunConfig {
    pub input: Option<String>,
    pub input_file: Option<String>,
    pub thread_id: String,
    pub stream: bool,
    pub log_level: String,
}

impl Default for RunConfig {
    fn default() -> Self {
        Self {
            input: None,
            input_file: None,
            thread_id: "default".to_string(),
            stream: false,
            log_level: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct InteractionConfig {
    pub source: String,
    pub session_id: Option<String>,
    pub actor_id: Option<String>,
    pub reply_to: Option<String>,
    pub audience: String,
    pub interactive: bool,
    pub locale: Option<String>,
    pub raw: BTreeMap<String, Value>,
}

impl Default for InteractionConfig {
    fn default() -> Self {
        Self {
            source: "cli".to_string(),
            session_id: None,
            actor_id: None,
            reply_to: None,
            audience: "user".to_string(),
            interactive: false,
            locale: None,
            raw: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct OutputConfig {
    pub format: String,
    pub show_events: bool,
    pub events_file: Option<String>,
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self {
            format: "text".to_string(),
            show_events: false,
            events_file: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Loop0RunConfig {
    pub prompt: PromptConfig,
    pub provider: ProviderConfig,
    pub policy: PolicyConfig,
    pub agent: AgentConfig,
    pub run: RunConfig,
    pub interaction: InteractionConfig,
    pub output: OutputConfig,
    pub env_file: Option<String>,
    #[serde(skip)]
    pub base_dir: PathBuf,
}

impl Default for Loop0RunConfig {
    fn default() -> Self {
        Self {
            prompt: PromptConfig::default(),
            provider: ProviderConfig::default(),
            policy: PolicyConfig::default(),
            agent: AgentConfig::default(),
            run: RunConfig::default(),
            interaction: InteractionConfig::default(),
            output: OutputConfig::default(),
            env_file: None,
            base_dir: std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")),
        }
    }
}

impl Loop0RunConfig {
    pub fn from_file(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let text = fs::read_to_string(path)
            .with_context(|| format!("failed to read config file {}", path.display()))?;
        let mut config: Self = match path.extension().and_then(|ext| ext.to_str()) {
            Some("json") => serde_json::from_str(&text)
                .with_context(|| format!("failed to parse JSON config {}", path.display()))?,
            Some("toml") | Some("tml") => toml::from_str(&text)
                .with_context(|| format!("failed to parse TOML config {}", path.display()))?,
            _ => return Err(anyhow!("config file must be .json or .toml")),
        };
        config.base_dir = path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from("."));
        Ok(config)
    }

    pub fn load_prompt_system(&self) -> Result<String> {
        read_optional_text(
            &self.base_dir,
            self.prompt.system_file.as_deref(),
            &self.prompt.system,
        )
    }

    pub fn load_prompt_user(&self) -> Result<String> {
        read_optional_text(
            &self.base_dir,
            self.prompt.user_file.as_deref(),
            &self.prompt.user,
        )
    }

    pub fn load_input(&self) -> Result<String> {
        if let Some(path) = &self.run.input_file {
            return fs::read_to_string(resolve_path(&self.base_dir, path))
                .with_context(|| format!("failed to read input file {path}"));
        }
        self.run
            .input
            .clone()
            .ok_or_else(|| anyhow!("missing input; set run.input or run.input_file"))
    }

    pub fn workspace_path(&self) -> PathBuf {
        resolve_path(&self.base_dir, &self.agent.workspace)
    }

    pub fn events_path(&self) -> Option<PathBuf> {
        self.output
            .events_file
            .as_ref()
            .map(|path| resolve_path(&self.base_dir, path))
    }
}

pub fn resolve_path(base_dir: &Path, path: &str) -> PathBuf {
    let path = PathBuf::from(path);
    if path.is_absolute() {
        return path;
    }
    base_dir.join(path)
}

fn read_optional_text(base_dir: &Path, path: Option<&str>, fallback: &str) -> Result<String> {
    if let Some(path) = path {
        return fs::read_to_string(resolve_path(base_dir, path))
            .with_context(|| format!("failed to read text file {path}"));
    }
    Ok(fallback.to_string())
}
