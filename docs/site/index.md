---
layout: home

hero:
  name: Loops
  text: Human Loop Protocol
  tagline: "A protocol for accountable human-agent work: task ownership, checkpoints, reviews, artifacts, ledgers, and audit."
  image:
    src: /logo.svg
    alt: Loops protocol mark
  actions:
    - theme: brand
      text: Read the HLP Spec
      link: /specs/hlp
    - theme: brand
      text: View Integration Contracts
      link: /specs/contracts
---

<section class="protocol-brief">
  <div class="brief-copy">
    <p class="eyebrow">Version 0.1.0-draft</p>
    <h2>The missing protocol surface is not tools or agents. It is accountability.</h2>
    <p>
      HLP defines how a human principal delegates bounded work to autonomous
      agents, pauses execution for decisions, reviews artifacts, and replays the
      entire lifecycle through audit.
    </p>
  </div>
  <div class="brief-panel" aria-label="HLP scope summary">
    <div>
      <strong>Defines</strong>
      <span>Task ownership, checkpoints, reviews, artifacts, ledger, audit</span>
    </div>
    <div>
      <strong>Routes to</strong>
      <span>A2A, ACP, AGNTCY, MCP, Agent Skills, local tools</span>
    </div>
    <div>
      <strong>Does not replace</strong>
      <span>Agent runtimes, tool protocols, transports, RBAC, UI channels</span>
    </div>
  </div>
</section>

<section class="route-cards" aria-label="Primary reading routes">
  <a class="route-card" href="./overview">
    <strong>Understand HLP</strong>
    <span>Read the positioning, object model, and why human-loop work needs its own protocol.</span>
  </a>
  <a class="route-card" href="./specs/hlp">
    <strong>Implement HLP</strong>
    <span>Use the complete HLP specification for tasks, checkpoints, reviews, artifacts, ledger, and audit.</span>
  </a>
  <a class="route-card" href="./specs/contracts">
    <strong>Bridge downward</strong>
    <span>Map HLP task identity and checkpoints into existing agent and capability protocols.</span>
  </a>
  <a class="route-card" href="./reading-routes">
    <strong>Choose a route</strong>
    <span>Start with HLP, then pick the L1/L0 ecosystem adapters your host already uses.</span>
  </a>
</section>

<section class="object-strip" aria-label="HLP first-class objects">
  <span>Task</span>
  <span>Checkpoint</span>
  <span>Ownership</span>
  <span>Review</span>
  <span>Artifact</span>
  <span>Ledger</span>
  <span>Audit</span>
</section>

<section class="stack-diagram" aria-label="HLP integration stack">
  <div class="section-heading">
    <p class="eyebrow">Integration model</p>
    <h2>HLP owns the human loop. Existing ecosystems keep execution.</h2>
  </div>
  <img class="stack-art" src="./assets/stack.svg" alt="Human Loop Protocol integration diagram: HLP above existing agent and capability protocol routes.">
  <p class="stack-caption">L1 and L0 pages are integration routes. They explain how HLP preserves task identity, checkpoint control, and capability provenance without defining another agent or tool protocol.</p>
</section>

<section class="layer-cards" aria-label="Protocol layers">
  <a class="layer-card l2" href="./specs/hlp">
    <span class="badge">L2</span>
    <h3>HLP</h3>
    <p>The only full protocol defined by this project: human-owned tasks, checkpoints, reviews, artifacts, ledger, and audit.</p>
  </a>
  <a class="layer-card l1" href="./specs/aap">
    <span class="badge">L1</span>
    <h3>Agent routes</h3>
    <p>Introductory routing guidance for A2A, AGNTCY-style meshes, ACP-style brokers, and custom agent runtimes.</p>
  </a>
  <a class="layer-card l0" href="./specs/cap">
    <span class="badge">L0</span>
    <h3>Capability routes</h3>
    <p>Introductory routing guidance for MCP, Agent Skills, local tools, and function-calling registries.</p>
  </a>
</section>

<section class="protocol-grid">
  <article>
    <h2>What HLP standardizes</h2>
    <ul>
      <li>Human-agent work units with stable task identity.</li>
      <li>Decision checkpoints that pause agent work until a human resolves them.</li>
      <li>Reviewable artifacts with immutable versions and provenance.</li>
      <li>Audit trails that can replay every protocol operation.</li>
      <li>Layer contracts that keep implementation details from crossing boundaries.</li>
    </ul>
  </article>
  <article>
    <h2>What HLP does not replace</h2>
    <ul>
      <li>MCP servers and Skills runtimes remain the natural L0 implementations.</li>
      <li>A2A, ACP, and agent meshes remain natural L1 implementations.</li>
      <li>Host platforms still choose transport, persistence, identity, RBAC, and UI.</li>
      <li>Agent runtimes remain free to choose models, prompts, tools, and execution loops.</li>
    </ul>
  </article>
</section>

<section class="contract-band" aria-label="Integration contracts">
  <div class="section-heading">
    <p class="eyebrow">Boundary rules</p>
    <h2>Four contracts keep the stack replaceable.</h2>
  </div>
  <div class="contract-grid">
    <a href="./specs/contracts#contract-1-capabilityref">
      <strong>CapabilityRef</strong>
      <span>Capabilities are referenced by id and version, never transport.</span>
    </a>
    <a href="./specs/contracts#contract-2-taskid-correlation">
      <strong>TaskID correlation</strong>
      <span>The HLP task id survives every delegated agent run.</span>
    </a>
    <a href="./specs/contracts#contract-3-checkpoint-to-block">
      <strong>Checkpoint to block</strong>
      <span>Human decisions pause and resume the corresponding run.</span>
    </a>
    <a href="./specs/contracts#contract-4-ownership-to-handoff">
      <strong>Ownership to handoff</strong>
      <span>Responsibility changes preserve execution correlation.</span>
    </a>
  </div>
</section>

<section class="adoption-strip">
  <h2>Start with the human loop</h2>
  <p>
    Platforms that need accountable human-agent work should implement HLP
    directly. Agent runtimes and capability providers stay on their existing
    protocols; HLP only requires narrow adapter contracts at the boundary.
  </p>
  <p><a href="./specs/hlp">Read the HLP spec</a> or <a href="./protocol-map">view the integration map</a>.</p>
</section>
