use std::collections::BTreeMap;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::loop0::types::Message;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryRecord {
    pub id: String,
    pub content: String,
    pub scope: String,
    pub kind: String,
    pub metadata: BTreeMap<String, Value>,
    pub importance: f64,
    pub pinned: bool,
    pub created_at: chrono::DateTime<chrono::Utc>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl MemoryRecord {
    pub fn new(content: impl Into<String>) -> Self {
        let now = Utc::now();
        Self {
            id: format!("mem_{}", Uuid::new_v4().simple()),
            content: content.into(),
            scope: "agent".to_string(),
            kind: "fact".to_string(),
            metadata: BTreeMap::new(),
            importance: 0.5,
            pinned: false,
            created_at: now,
            updated_at: now,
        }
    }

    pub fn matches(&self, query: &str) -> bool {
        query.is_empty() || self.content.to_lowercase().contains(&query.to_lowercase())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreadState {
    pub thread_id: String,
    pub messages: Vec<Message>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl ThreadState {
    pub fn new(thread_id: impl Into<String>) -> Self {
        Self {
            thread_id: thread_id.into(),
            messages: Vec::new(),
            updated_at: Utc::now(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentState {
    pub agent_id: String,
    pub threads: BTreeMap<String, ThreadState>,
    pub memories: BTreeMap<String, MemoryRecord>,
    pub artifacts: BTreeMap<String, Value>,
    pub component_state: BTreeMap<String, Value>,
    pub checkpoints: BTreeMap<String, Value>,
    pub updated_at: chrono::DateTime<chrono::Utc>,
}

impl Default for AgentState {
    fn default() -> Self {
        Self {
            agent_id: format!("agent_{}", Uuid::new_v4().simple()),
            threads: BTreeMap::new(),
            memories: BTreeMap::new(),
            artifacts: BTreeMap::new(),
            component_state: BTreeMap::new(),
            checkpoints: BTreeMap::new(),
            updated_at: Utc::now(),
        }
    }
}

impl AgentState {
    pub fn append_message(&mut self, thread_id: &str, message: Message) {
        let now = Utc::now();
        let thread = self
            .threads
            .entry(thread_id.to_string())
            .or_insert_with(|| ThreadState::new(thread_id));
        thread.messages.push(message);
        thread.updated_at = now;
        self.updated_at = now;
    }

    pub fn get_history(&self, thread_id: &str, window: Option<usize>) -> Vec<Message> {
        let Some(thread) = self.threads.get(thread_id) else {
            return Vec::new();
        };
        if let Some(window) = window {
            return thread
                .messages
                .iter()
                .skip(thread.messages.len().saturating_sub(window))
                .cloned()
                .collect();
        }
        thread.messages.clone()
    }

    pub fn remember(&mut self, record: MemoryRecord) -> MemoryRecord {
        self.updated_at = Utc::now();
        self.memories.insert(record.id.clone(), record.clone());
        record
    }

    pub fn recall(&self, query: &str, limit: usize) -> Vec<MemoryRecord> {
        let mut matches = self
            .memories
            .values()
            .filter(|record| record.matches(query))
            .cloned()
            .collect::<Vec<_>>();
        matches.sort_by(|left, right| {
            right
                .pinned
                .cmp(&left.pinned)
                .then_with(|| right.importance.total_cmp(&left.importance))
                .then_with(|| right.updated_at.cmp(&left.updated_at))
        });
        matches.truncate(limit);
        matches
    }
}
