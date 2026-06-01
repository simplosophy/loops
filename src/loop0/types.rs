use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCall {
    pub name: String,
    #[serde(default)]
    pub arguments: Value,
    pub id: String,
    #[serde(default)]
    pub raw: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: String,
    #[serde(default)]
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_calls: Vec<ToolCall>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub metadata: BTreeMap<String, Value>,
}

impl Message {
    pub fn new(role: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            role: role.into(),
            content: content.into(),
            name: None,
            tool_call_id: None,
            tool_calls: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }

    pub fn tool(content: impl Into<String>, tool_call_id: impl Into<String>) -> Self {
        Self {
            role: "tool".to_string(),
            content: content.into(),
            name: None,
            tool_call_id: Some(tool_call_id.into()),
            tool_calls: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserInput {
    pub text: String,
    #[serde(default)]
    pub attachments: Vec<Value>,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
    #[serde(default)]
    pub interaction_context: InteractionContext,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InteractionContext {
    pub source: String,
    pub session_id: Option<String>,
    pub thread_id: Option<String>,
    pub actor_id: Option<String>,
    pub reply_to: Option<String>,
    pub audience: String,
    pub interactive: bool,
    pub stream: bool,
    pub locale: Option<String>,
    #[serde(default)]
    pub raw: BTreeMap<String, Value>,
}

impl Default for InteractionContext {
    fn default() -> Self {
        Self {
            source: "direct".to_string(),
            session_id: None,
            thread_id: None,
            actor_id: None,
            reply_to: None,
            audience: "user".to_string(),
            interactive: false,
            stream: false,
            locale: None,
            raw: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEvent {
    pub r#type: String,
    pub run_id: String,
    #[serde(default)]
    pub payload: Value,
    pub event_id: String,
    pub timestamp: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeStats {
    pub turns: usize,
    pub tool_calls: usize,
    pub input_tokens: usize,
    pub output_tokens: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentResult {
    pub output: String,
    pub run_id: String,
    pub thread_id: String,
    pub stop_reason: String,
    pub stats: RuntimeStats,
    #[serde(default)]
    pub events: Vec<AgentEvent>,
}

impl Default for RuntimeStats {
    fn default() -> Self {
        Self {
            turns: 0,
            tool_calls: 0,
            input_tokens: 0,
            output_tokens: 0,
        }
    }
}
