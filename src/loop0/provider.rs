use std::collections::BTreeMap;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use async_trait::async_trait;
use futures_util::StreamExt;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::loop0::config::ProviderConfig;
use crate::loop0::types::{Message, ToolCall};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolProfile {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

#[derive(Debug, Clone)]
pub struct ProviderRequest {
    pub messages: Vec<Message>,
    pub tools: Vec<ToolProfile>,
    pub stream: bool,
    pub parallel_tool_calls: Option<bool>,
}

#[derive(Debug, Clone)]
pub struct ProviderResponse {
    pub content: String,
    pub tool_calls: Vec<ToolCall>,
    pub stop_reason: Option<String>,
    pub raw: Value,
}

#[derive(Debug, Clone)]
pub enum ProviderStreamEvent {
    TextDelta(String),
    ReasoningDelta(String),
}

#[derive(Debug, Clone)]
pub struct ProviderOutput {
    pub response: ProviderResponse,
    pub events: Vec<ProviderStreamEvent>,
}

#[async_trait]
pub trait ProviderClient: Send + Sync {
    async fn complete(&self, request: ProviderRequest) -> Result<ProviderOutput>;
}

#[derive(Clone)]
pub struct OpenAiCompatibleProvider {
    config: ProviderConfig,
    client: reqwest::Client,
}

impl OpenAiCompatibleProvider {
    pub fn new(config: ProviderConfig) -> Result<Self> {
        if config.kind != "openai-compatible" {
            return Err(anyhow!("unsupported provider type: {}", config.kind));
        }
        if config.api_key.is_empty() {
            return Err(anyhow!(
                "missing provider API key; set {} or pass --api-key",
                config.api_key_env
            ));
        }
        if config.model.is_empty() {
            return Err(anyhow!("missing provider model"));
        }
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs_f64(config.timeout_seconds))
            .danger_accept_invalid_certs(config.disable_verify_ssl)
            .build()
            .context("failed to build HTTP client")?;
        Ok(Self { config, client })
    }

    pub async fn generate(&self, request: ProviderRequest) -> Result<ProviderResponse> {
        let endpoint = format!(
            "{}/chat/completions",
            self.config.base_url.trim_end_matches('/')
        );
        let payload = self.build_payload(request, false);
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str(&format!("Bearer {}", self.config.api_key))
                .context("invalid authorization header")?,
        );
        for (key, value) in &self.config.headers {
            headers.insert(
                HeaderName::from_bytes(key.as_bytes())
                    .with_context(|| format!("invalid header name: {key}"))?,
                HeaderValue::from_str(value)
                    .with_context(|| format!("invalid header value for {key}"))?,
            );
        }
        let response = self
            .client
            .post(&endpoint)
            .headers(headers)
            .json(&payload)
            .send()
            .await
            .with_context(|| format!("provider request failed for {endpoint}"))?;
        let status = response.status();
        let body = response
            .text()
            .await
            .context("failed to read provider response body")?;
        if !status.is_success() {
            return Err(anyhow!("provider HTTP {status} from {endpoint}: {body}"));
        }
        let raw: Value =
            serde_json::from_str(&body).context("failed to parse provider response JSON")?;
        response_from_openai(raw)
    }

    pub async fn stream(&self, request: ProviderRequest) -> Result<ProviderOutput> {
        let endpoint = format!(
            "{}/chat/completions",
            self.config.base_url.trim_end_matches('/')
        );
        let payload = self.build_payload(request, true);
        let response = self
            .client
            .post(&endpoint)
            .headers(self.headers()?)
            .json(&payload)
            .send()
            .await
            .with_context(|| format!("provider request failed for {endpoint}"))?;
        let status = response.status();
        if !status.is_success() {
            let body = response
                .text()
                .await
                .context("failed to read provider response body")?;
            return Err(anyhow!("provider HTTP {status} from {endpoint}: {body}"));
        }
        let mut content_parts = Vec::new();
        let mut reasoning_parts = Vec::new();
        let mut tool_call_chunks = BTreeMap::new();
        let mut stop_reason = None;
        let mut raw_chunks = Vec::new();
        let mut events = Vec::new();
        let mut buffer = String::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.context("failed to read provider stream chunk")?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));
            while let Some(index) = buffer.find('\n') {
                let line = buffer[..index].trim().to_string();
                buffer = buffer[index + 1..].to_string();
                if line.is_empty() || line.starts_with(':') || !line.starts_with("data:") {
                    continue;
                }
                let data = line["data:".len()..].trim();
                if data == "[DONE]" {
                    continue;
                }
                let chunk: Value = serde_json::from_str(data)
                    .with_context(|| format!("failed to parse provider stream chunk: {data}"))?;
                collect_stream_chunk(
                    &chunk,
                    &mut content_parts,
                    &mut reasoning_parts,
                    &mut tool_call_chunks,
                    &mut stop_reason,
                    &mut events,
                );
                raw_chunks.push(chunk);
            }
        }
        let content = content_parts.join("");
        let response = ProviderResponse {
            content,
            tool_calls: tool_calls_from_stream_chunks(&tool_call_chunks),
            stop_reason,
            raw: json!({"chunks": raw_chunks, "reasoning_content": reasoning_parts.join("")}),
        };
        Ok(ProviderOutput { response, events })
    }

    fn build_payload(&self, request: ProviderRequest, stream: bool) -> Value {
        let mut object = serde_json::Map::new();
        object.insert(
            "model".to_string(),
            Value::String(self.config.model.clone()),
        );
        object.insert(
            "messages".to_string(),
            Value::Array(request.messages.iter().map(message_to_openai).collect()),
        );
        if !request.tools.is_empty() {
            object.insert(
                "tools".to_string(),
                Value::Array(request.tools.iter().map(tool_to_openai).collect()),
            );
            if let Some(parallel) = request.parallel_tool_calls {
                object.insert("parallel_tool_calls".to_string(), Value::Bool(parallel));
            }
        }
        if stream {
            object.insert("stream".to_string(), Value::Bool(true));
        }
        if let Some(reasoning_effort) = &self.config.reasoning_effort {
            object.insert(
                "reasoning_effort".to_string(),
                Value::String(reasoning_effort.clone()),
            );
        }
        for (key, value) in &self.config.extra_body {
            object.insert(key.clone(), value.clone());
        }
        Value::Object(object)
    }

    fn headers(&self) -> Result<HeaderMap> {
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_str(&format!("Bearer {}", self.config.api_key))
                .context("invalid authorization header")?,
        );
        for (key, value) in &self.config.headers {
            headers.insert(
                HeaderName::from_bytes(key.as_bytes())
                    .with_context(|| format!("invalid header name: {key}"))?,
                HeaderValue::from_str(value)
                    .with_context(|| format!("invalid header value for {key}"))?,
            );
        }
        Ok(headers)
    }
}

#[async_trait]
impl ProviderClient for OpenAiCompatibleProvider {
    async fn complete(&self, request: ProviderRequest) -> Result<ProviderOutput> {
        if request.stream {
            return self.stream(request).await;
        }
        let response = self.generate(request).await?;
        Ok(ProviderOutput {
            response,
            events: Vec::new(),
        })
    }
}

fn message_to_openai(message: &Message) -> Value {
    let mut object = serde_json::Map::new();
    object.insert("role".to_string(), Value::String(message.role.clone()));
    object.insert(
        "content".to_string(),
        Value::String(message.content.clone()),
    );
    if let Some(tool_call_id) = &message.tool_call_id {
        object.insert(
            "tool_call_id".to_string(),
            Value::String(tool_call_id.clone()),
        );
    }
    if !message.tool_calls.is_empty() {
        object.insert(
            "tool_calls".to_string(),
            Value::Array(message.tool_calls.iter().map(tool_call_to_openai).collect()),
        );
    }
    Value::Object(object)
}

fn tool_call_to_openai(tool_call: &ToolCall) -> Value {
    json!({
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments.to_string(),
        }
    })
}

fn tool_to_openai(tool: &ToolProfile) -> Value {
    json!({
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }
    })
}

fn response_from_openai(raw: Value) -> Result<ProviderResponse> {
    let choice = raw
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|choices| choices.first())
        .ok_or_else(|| anyhow!("provider response did not include choices[0]"))?;
    let message = choice
        .get("message")
        .ok_or_else(|| anyhow!("provider response did not include choices[0].message"))?;
    let content = message
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let stop_reason = choice
        .get("finish_reason")
        .and_then(Value::as_str)
        .map(ToString::to_string);
    let tool_calls = message
        .get("tool_calls")
        .and_then(Value::as_array)
        .map(|values| parse_tool_calls(values))
        .transpose()?
        .unwrap_or_default();
    Ok(ProviderResponse {
        content,
        tool_calls,
        stop_reason,
        raw,
    })
}

fn parse_tool_calls(values: &[Value]) -> Result<Vec<ToolCall>> {
    values.iter().map(parse_tool_call).collect()
}

fn parse_tool_call(value: &Value) -> Result<ToolCall> {
    let id = value
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("call")
        .to_string();
    let function = value
        .get("function")
        .ok_or_else(|| anyhow!("tool call missing function"))?;
    let name = function
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("tool call missing function.name"))?
        .to_string();
    let arguments_text = function
        .get("arguments")
        .and_then(Value::as_str)
        .unwrap_or("{}");
    let arguments = parse_tool_arguments(arguments_text);
    Ok(ToolCall {
        name,
        arguments,
        id,
        raw: value.clone(),
    })
}

#[derive(Debug, Default)]
struct StreamToolCallChunk {
    id: String,
    name: String,
    arguments: String,
    raw_deltas: Vec<Value>,
}

fn collect_stream_chunk(
    chunk: &Value,
    content_parts: &mut Vec<String>,
    reasoning_parts: &mut Vec<String>,
    tool_call_chunks: &mut BTreeMap<usize, StreamToolCallChunk>,
    stop_reason: &mut Option<String>,
    events: &mut Vec<ProviderStreamEvent>,
) {
    let Some(choice) = chunk
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|choices| choices.first())
    else {
        return;
    };
    if let Some(reason) = choice.get("finish_reason").and_then(Value::as_str) {
        if !reason.is_empty() {
            *stop_reason = Some(reason.to_string());
        }
    }
    let Some(delta) = choice.get("delta") else {
        return;
    };
    if let Some(text) = delta.get("content").and_then(Value::as_str) {
        if !text.is_empty() {
            content_parts.push(text.to_string());
            events.push(ProviderStreamEvent::TextDelta(text.to_string()));
        }
    }
    if let Some(text) = delta.get("reasoning_content").and_then(Value::as_str) {
        if !text.is_empty() {
            reasoning_parts.push(text.to_string());
            events.push(ProviderStreamEvent::ReasoningDelta(text.to_string()));
        }
    }
    if let Some(tool_call_deltas) = delta.get("tool_calls").and_then(Value::as_array) {
        merge_tool_call_deltas(tool_call_chunks, tool_call_deltas);
    }
}

fn merge_tool_call_deltas(target: &mut BTreeMap<usize, StreamToolCallChunk>, deltas: &[Value]) {
    for delta in deltas {
        let index = delta.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
        let current = target.entry(index).or_default();
        if let Some(id) = delta.get("id").and_then(Value::as_str) {
            if !id.is_empty() {
                current.id = id.to_string();
            }
        }
        if let Some(function) = delta.get("function") {
            if let Some(name) = function.get("name").and_then(Value::as_str) {
                if !name.is_empty() {
                    current.name = name.to_string();
                }
            }
            if let Some(arguments) = function.get("arguments").and_then(Value::as_str) {
                current.arguments.push_str(arguments);
            }
        }
        current.raw_deltas.push(delta.clone());
    }
}

fn tool_calls_from_stream_chunks(chunks: &BTreeMap<usize, StreamToolCallChunk>) -> Vec<ToolCall> {
    chunks
        .iter()
        .map(|(index, chunk)| ToolCall {
            name: chunk.name.clone(),
            arguments: parse_tool_arguments(&chunk.arguments),
            id: if chunk.id.is_empty() {
                format!("call_{index}")
            } else {
                chunk.id.clone()
            },
            raw: json!({
                "index": index,
                "id": chunk.id,
                "function": {
                    "name": chunk.name,
                    "arguments": chunk.arguments,
                },
                "deltas": chunk.raw_deltas,
            }),
        })
        .collect()
}

fn parse_tool_arguments(arguments_text: &str) -> Value {
    serde_json::from_str(arguments_text).unwrap_or_else(|_| {
        let mut fallback = BTreeMap::new();
        fallback.insert("raw".to_string(), Value::String(arguments_text.to_string()));
        serde_json::to_value(fallback).unwrap_or(Value::Null)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn folds_streaming_tool_call_deltas() {
        let chunks = vec![
            json!({
                "choices": [{
                    "delta": {
                        "content": "working",
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_echo",
                            "type": "function",
                            "function": {"name": "echo", "arguments": ""}
                        }]
                    }
                }]
            }),
            json!({
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"arguments": "{\"value\""}
                        }]
                    }
                }]
            }),
            json!({
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "function": {"arguments": ":\"hello\"}"}
                        }]
                    },
                    "finish_reason": "tool_calls"
                }]
            }),
        ];
        let mut content_parts = Vec::new();
        let mut reasoning_parts = Vec::new();
        let mut tool_call_chunks = BTreeMap::new();
        let mut stop_reason = None;
        let mut events = Vec::new();

        for chunk in &chunks {
            collect_stream_chunk(
                chunk,
                &mut content_parts,
                &mut reasoning_parts,
                &mut tool_call_chunks,
                &mut stop_reason,
                &mut events,
            );
        }

        let tool_calls = tool_calls_from_stream_chunks(&tool_call_chunks);
        assert_eq!(content_parts.join(""), "working");
        assert_eq!(stop_reason.as_deref(), Some("tool_calls"));
        assert_eq!(tool_calls.len(), 1);
        assert_eq!(tool_calls[0].id, "call_echo");
        assert_eq!(tool_calls[0].name, "echo");
        assert_eq!(tool_calls[0].arguments["value"], "hello");
        assert!(matches!(events[0], ProviderStreamEvent::TextDelta(_)));
    }
}
