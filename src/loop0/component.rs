use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::loop0::tool::ToolExecutor;
use crate::loop0::types::{AgentEvent, InteractionContext, UserInput};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentProfile {
    pub name: String,
    pub kind: String,
    pub priority: i32,
    pub metadata: BTreeMap<String, Value>,
}

impl ComponentProfile {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            kind: "component".to_string(),
            priority: 0,
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Default)]
pub struct Contribution {
    pub prompt_blocks: Vec<String>,
    pub tools: Vec<Arc<dyn ToolExecutor>>,
    pub metadata: BTreeMap<String, Value>,
}

#[derive(Debug, Clone)]
pub struct RunContext {
    pub run_id: String,
    pub thread_id: String,
    pub input: UserInput,
    pub interaction: InteractionContext,
    pub workspace: PathBuf,
    pub metadata: BTreeMap<String, Value>,
}

#[async_trait]
pub trait Component: Send + Sync {
    fn profile(&self) -> ComponentProfile {
        ComponentProfile::new("component")
    }

    async fn setup(&self) -> Result<()> {
        Ok(())
    }

    async fn contribute(&self, _ctx: &RunContext) -> Result<Contribution> {
        Ok(Contribution::default())
    }

    async fn handle_event(&self, _event: &AgentEvent) -> Result<()> {
        Ok(())
    }

    async fn teardown(&self) -> Result<()> {
        Ok(())
    }
}
