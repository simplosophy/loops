use std::collections::BTreeMap;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::loop0::types::{AgentEvent, UserInput};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelMessage {
    pub message_id: String,
    pub channel_id: String,
    pub user_id: String,
    pub conversation_id: String,
    pub text: String,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
    pub received_at: chrono::DateTime<chrono::Utc>,
}

impl ChannelMessage {
    pub fn new(
        channel_id: impl Into<String>,
        user_id: impl Into<String>,
        conversation_id: impl Into<String>,
        text: impl Into<String>,
    ) -> Self {
        Self {
            message_id: format!("msg_{}", Uuid::new_v4().simple()),
            channel_id: channel_id.into(),
            user_id: user_id.into(),
            conversation_id: conversation_id.into(),
            text: text.into(),
            metadata: BTreeMap::new(),
            received_at: Utc::now(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelOutput {
    pub channel_id: String,
    pub conversation_id: String,
    pub reply_to: Option<String>,
    pub text: String,
    #[serde(default)]
    pub events: Vec<AgentEvent>,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionState {
    pub session_id: String,
    pub user_id: String,
    pub channel_id: String,
    pub conversation_id: String,
    pub active_agent_id: Option<String>,
    #[serde(default)]
    pub thread_map: BTreeMap<String, String>,
    #[serde(default)]
    pub pending_approvals: BTreeMap<String, Value>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl SessionState {
    pub fn new(
        user_id: impl Into<String>,
        channel_id: impl Into<String>,
        conversation_id: impl Into<String>,
    ) -> Self {
        Self {
            session_id: format!("ses_{}", Uuid::new_v4().simple()),
            user_id: user_id.into(),
            channel_id: channel_id.into(),
            conversation_id: conversation_id.into(),
            active_agent_id: None,
            thread_map: BTreeMap::new(),
            pending_approvals: BTreeMap::new(),
            updated_at: Utc::now(),
        }
    }

    pub fn bind_agent_thread(&mut self, agent_id: impl Into<String>, thread_id: impl Into<String>) {
        let agent_id = agent_id.into();
        self.active_agent_id = Some(agent_id.clone());
        self.thread_map.insert(agent_id, thread_id.into());
        self.updated_at = Utc::now();
    }

    pub fn active_thread_id(&self) -> Option<&str> {
        self.active_agent_id
            .as_ref()
            .and_then(|agent_id| self.thread_map.get(agent_id))
            .map(String::as_str)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoopContainerState {
    pub user_id: String,
    #[serde(default)]
    pub sessions: BTreeMap<String, SessionState>,
    #[serde(default)]
    pub agent_ids: Vec<String>,
}

impl LoopContainerState {
    pub fn new(user_id: impl Into<String>) -> Self {
        Self {
            user_id: user_id.into(),
            sessions: BTreeMap::new(),
            agent_ids: Vec::new(),
        }
    }

    pub fn upsert_session(&mut self, session: SessionState) {
        self.sessions.insert(session.session_id.clone(), session);
    }
}

pub trait Channel: Send + Sync {
    fn name(&self) -> &str;
    fn map_input(&self, message: ChannelMessage, session: &SessionState) -> UserInput;
    fn map_output(&self, output: ChannelOutput) -> Value;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_tracks_active_agent_thread() {
        let mut session = SessionState::new("user-a", "cli", "conversation-a");
        assert!(session.active_thread_id().is_none());

        session.bind_agent_thread("agent-a", "thread-a");

        assert_eq!(session.active_agent_id.as_deref(), Some("agent-a"));
        assert_eq!(session.active_thread_id(), Some("thread-a"));
    }
}
