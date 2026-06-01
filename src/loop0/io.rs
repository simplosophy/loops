use anyhow::Result;

use crate::loop0::types::AgentEvent;

pub trait EventSink {
    fn send(&mut self, event: &AgentEvent) -> Result<()>;
}

#[derive(Debug, Default)]
pub struct NullEventSink;

impl EventSink for NullEventSink {
    fn send(&mut self, _event: &AgentEvent) -> Result<()> {
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct InMemoryEventSink {
    pub events: Vec<AgentEvent>,
}

impl EventSink for InMemoryEventSink {
    fn send(&mut self, event: &AgentEvent) -> Result<()> {
        self.events.push(event.clone());
        Ok(())
    }
}
