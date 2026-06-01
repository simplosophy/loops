use chrono::Utc;
use serde_json::Value;
use uuid::Uuid;

use crate::loop0::types::AgentEvent;

pub fn agent_event(event_type: impl Into<String>, run_id: &str, payload: Value) -> AgentEvent {
    AgentEvent {
        r#type: event_type.into(),
        run_id: run_id.to_string(),
        payload,
        event_id: format!("evt_{}", Uuid::new_v4().simple()),
        timestamp: Utc::now(),
    }
}
