use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use async_trait::async_trait;
use serde_json::Value;

use crate::loop0::config::PolicyConfig;
use crate::loop0::provider::ToolProfile;
use crate::loop0::shell::{execute_shell_tool, shell_tool_profile};
use crate::loop0::types::{AgentEvent, ToolCall};

#[derive(Debug, Clone)]
pub struct ToolResult {
    pub output: String,
    pub error: Option<String>,
    pub status: String,
    pub metadata: BTreeMap<String, Value>,
}

impl ToolResult {
    pub fn success(output: impl Into<String>) -> Self {
        Self {
            output: output.into(),
            error: None,
            status: "success".to_string(),
            metadata: BTreeMap::new(),
        }
    }

    pub fn failure(error: impl Into<String>, status: impl Into<String>) -> Self {
        Self {
            output: String::new(),
            error: Some(error.into()),
            status: status.into(),
            metadata: BTreeMap::new(),
        }
    }

    pub fn is_success(&self) -> bool {
        self.status == "success" && self.error.is_none()
    }

    pub fn message_content(&self) -> String {
        if self.is_success() {
            self.output.clone()
        } else {
            format!(
                "Error: {}",
                self.error.clone().unwrap_or_else(|| self.status.clone())
            )
        }
    }
}

pub struct ToolContext<'a> {
    pub agent_id: String,
    pub run_id: String,
    pub workspace: PathBuf,
    pub policy: &'a PolicyConfig,
    pub metadata: BTreeMap<String, Value>,
    pub emitted_events: Vec<AgentEvent>,
}

#[async_trait]
pub trait ToolExecutor: Send + Sync {
    fn profile(&self) -> ToolProfile;
    async fn execute(&self, ctx: &mut ToolContext<'_>, args: &Value) -> Result<ToolResult>;
}

#[derive(Clone, Default)]
pub struct ToolRegistry {
    tools: BTreeMap<String, Arc<dyn ToolExecutor>>,
}

impl ToolRegistry {
    pub fn register<T>(&mut self, tool: T) -> Result<()>
    where
        T: ToolExecutor + 'static,
    {
        self.register_arc(Arc::new(tool))
    }

    pub fn register_arc(&mut self, tool: Arc<dyn ToolExecutor>) -> Result<()> {
        let profile = tool.profile();
        if self.tools.contains_key(&profile.name) {
            anyhow::bail!("tool '{}' is already registered", profile.name);
        }
        self.tools.insert(profile.name, tool);
        Ok(())
    }

    pub fn extend_arc<I>(&mut self, tools: I) -> Result<()>
    where
        I: IntoIterator<Item = Arc<dyn ToolExecutor>>,
    {
        for tool in tools {
            self.register_arc(tool)?;
        }
        Ok(())
    }

    pub fn profiles(&self) -> Vec<ToolProfile> {
        self.tools.values().map(|tool| tool.profile()).collect()
    }

    pub async fn execute(
        &self,
        name: &str,
        ctx: &mut ToolContext<'_>,
        args: &Value,
    ) -> Result<ToolResult> {
        let Some(tool) = self.tools.get(name) else {
            return Ok(ToolResult::failure(
                format!("unknown tool: {name}"),
                "not_found",
            ));
        };
        match tool.execute(ctx, args).await {
            Ok(result) => Ok(result),
            Err(error) => Ok(ToolResult::failure(
                format!("error executing {name}: {error:#}"),
                "error",
            )),
        }
    }
}

pub fn registry_from_names(names: &[String]) -> Result<ToolRegistry> {
    let mut registry = ToolRegistry::default();
    for name in names {
        match name.as_str() {
            "shell" => registry.register(ShellTool)?,
            other => anyhow::bail!("unsupported tool: {other}"),
        }
    }
    Ok(registry)
}

#[derive(Clone)]
pub struct ShellTool;

#[async_trait]
impl ToolExecutor for ShellTool {
    fn profile(&self) -> ToolProfile {
        shell_tool_profile()
    }

    async fn execute(&self, ctx: &mut ToolContext<'_>, args: &Value) -> Result<ToolResult> {
        let tool_call = ToolCall {
            name: "shell".to_string(),
            arguments: args.clone(),
            id: "tool".to_string(),
            raw: Value::Null,
        };
        let output = execute_shell_tool(&tool_call, &ctx.workspace, ctx.policy).await?;
        Ok(ToolResult::success(output))
    }
}
