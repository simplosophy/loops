---
layout: home

hero:
  name: Loops
  text: Human Loop Protocol
  tagline: "An SDK and protocol for wrapping existing agent harnesses with accountable human interaction."
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
    <p class="eyebrow">Version 0.2.0-draft</p>
    <h2>The missing protocol surface is not tools or agents. It is accountability.</h2>
    <p>
      HLP defines how a human principal delegates bounded work to autonomous
      agent harnesses, pauses execution for decisions, reviews artifacts, and
      replays the entire lifecycle through audit.
    </p>
  </div>
  <div class="brief-panel" aria-label="HLP scope summary">
    <div>
      <strong>Defines</strong>
      <span>Task ownership, checkpoints, reviews, artifacts, ledger, audit</span>
    </div>
    <div>
      <strong>Routes to</strong>
      <span>Existing harnesses, A2A, ACP, AGNTCY, MCP, Agent Skills, local tools</span>
    </div>
    <div>
      <strong>Does not replace</strong>
      <span>Agent harnesses, tool protocols, transports, RBAC, UI channels</span>
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
    <strong>Wrap harnesses</strong>
    <span>Map HLP task identity, checkpoints, and harness events into existing harnesses.</span>
  </a>
  <a class="route-card" href="./reading-routes">
    <strong>Use the SDK</strong>
    <span>Start from the HLP host, then wire the harness adapters your platform already uses.</span>
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
    <h2>HLP owns human interaction semantics. Existing harnesses keep execution.</h2>
  </div>
  <img class="stack-art" src="./assets/stack.svg" alt="Human Loop Protocol integration diagram: HLP above existing agent and capability protocol routes.">
  <p class="stack-caption">L1 and L0 pages are integration routes. They explain how HLP preserves task identity, checkpoint control, harness event projection, and capability provenance without defining another agent or tool protocol.</p>
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
    <p>Introductory routing guidance for A2A, AGNTCY-style meshes, ACP-style brokers, and existing agent harnesses.</p>
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
      <li>Harness adapter contracts that keep implementation details from crossing boundaries.</li>
    </ul>
  </article>
  <article>
    <h2>What HLP does not replace</h2>
    <ul>
      <li>MCP servers and Skills runtimes remain the natural L0 implementations.</li>
      <li>A2A, ACP, and agent meshes remain natural L1 implementations.</li>
      <li>Host platforms still choose transport, persistence, identity, RBAC, and UI.</li>
      <li>Agent harnesses remain free to choose models, prompts, tools, memory, and execution loops.</li>
    </ul>
  </article>
</section>

<section class="sdk-strip" aria-label="HLP SDK surface">
  <div class="section-heading">
    <p class="eyebrow">SDK surface</p>
    <h2>Applications embed HLP as an SDK, not as an execution harness.</h2>
  </div>
  <div class="sdk-grid">
    <div>
      <strong>Public entry point</strong>
      <span><code>loops</code> and <code>loops.hlp</code> expose HLP protocol objects, <code>HLPClient</code>, <code>HLPHost</code>, stores, events, and adapters.</span>
    </div>
    <div>
      <strong>Runtime boundary</strong>
      <span><code>AgentAdapter</code> controls external harnesses; <code>HarnessAdapter</code> projects their human-facing events into HLP.</span>
    </div>
    <div>
      <strong>SDK boundary</strong>
      <span>Loops does not ship a built-in agent harness. Execution belongs to the harness you wrap.</span>
    </div>
  </div>
  <div class="sdk-code" aria-label="HLP host quickstart">
    <span>from loops import ArtifactPayload, CheckpointOption</span>
    <span>from loops import CodexCLIAdapter, HLPHost</span>
    <span></span>
    <span>host = HLPHost.in_memory(adapter=CodexCLIAdapter())</span>
    <span>client = host.client</span>
    <span></span>
    <span>task = await client.create_task(</span>
    <span>    principal="user_alice",</span>
    <span>    goal="Review PR #1234",</span>
    <span>)</span>
    <span>run = await client.delegate(task.id, "agent_codex")</span>
    <span>await client.start(task.id)</span>
    <span></span>
    <span>checkpoint = await client.raise_checkpoint(</span>
    <span>    task_id=task.id,</span>
    <span>    kind="choice",</span>
    <span>    prompt="Ship the patch?",</span>
    <span>    options=(CheckpointOption(id="safe", label="Review first"),),</span>
    <span>    raised_by=run.agent_id,</span>
    <span>)</span>
    <span>await client.resolve_checkpoint(</span>
    <span>    checkpoint.id, by="user_alice", action="choose", choice="safe"</span>
    <span>)</span>
    <span></span>
    <span>artifact = await client.commit_artifact(</span>
    <span>    task_id=task.id, type="report",</span>
    <span>    payload=ArtifactPayload(</span>
    <span>        kind="inline", uri="mem://report-v1", checksum="sha256:report-v1"</span>
    <span>    ),</span>
    <span>    produced_by=run.agent_id,</span>
    <span>)</span>
    <span>review = await client.submit_review(</span>
    <span>    task_id=task.id, artifact_id=artifact.id,</span>
    <span>    reviewer="user_alice", verdict="approved",</span>
    <span>)</span>
    <span>await client.write_ledger("project:web", "pr.1234", review.verdict, by=task.id)</span>
    <span>audit = await client.replay_audit(task.id)</span>
  </div>
</section>

<section class="sdk-strip" aria-label="First-class CLI harness adapters">
  <div class="section-heading">
    <p class="eyebrow">First-class adapters</p>
    <h2>Four agent CLIs share one harness projection pipeline.</h2>
    <p class="stack-caption">Codex, Pi, Claude Code, and Kimi wrap into HLP with the same JSONL projection of human-loop events, reliable peek/ack event delivery, and chat/protocol prompt modes — covered by offline contract suites and an opt-in live four-CLI lifecycle E2E.</p>
  </div>
  <table>
    <thead>
      <tr><th>CLI</th><th>Delegate adapter</th><th>Harness adapter (projection + peek/ack)</th><th>Wire mode</th></tr>
    </thead>
    <tbody>
      <tr><td>Codex</td><td><code>CodexCLIAdapter</code></td><td><code>CodexHarnessAdapter</code></td><td><code>codex exec --json</code></td></tr>
      <tr><td>Pi</td><td>—</td><td><code>PiHarnessAdapter</code></td><td><code>pi --mode json</code></td></tr>
      <tr><td>Claude Code</td><td><code>ClaudeCodeCLIAdapter</code></td><td><code>ClaudeCodeHarnessAdapter</code></td><td><code>claude -p --output-format stream-json</code></td></tr>
      <tr><td>Kimi</td><td><code>KimiCLIAdapter</code></td><td><code>KimiHarnessAdapter</code></td><td><code>kimi -p --output-format stream-json</code></td></tr>
    </tbody>
  </table>
  <p class="stack-caption">Sensor input such as brain-computer interfaces (BCI) is compatible by design (spec appendix C): a decoder is only a channel-plane producer of <code>ControlSignal</code> values, high-risk checkpoints cannot close on BCI alone (fail-closed, second factor supported), and the offline <code>loops-hlp-bci-demo</code> proves it — zero protocol changes.</p>
</section>

<section class="contract-band" aria-label="Integration contracts">
  <div class="section-heading">
    <p class="eyebrow">Boundary rules</p>
    <h2>Four contracts keep the stack replaceable.</h2>
  </div>
  <div class="contract-grid">
    <a href="./specs/contracts#contract-1-external-evidence-reference">
      <strong>External evidence</strong>
      <span>Capability evidence is optional, opaque, and never transport.</span>
    </a>
    <a href="./specs/contracts#contract-2-taskid-correlation">
      <strong>TaskID correlation</strong>
      <span>The HLP task id survives every delegated agent run.</span>
    </a>
    <a href="./specs/contracts#contract-3-checkpoint-to-block">
      <strong>Checkpoint to block</strong>
      <span>Human decisions pause and resume the corresponding run.</span>
    </a>
    <a href="./specs/contracts#contract-4-harness-event-projection">
      <strong>Harness event projection</strong>
      <span>Approval, input, and artifact events become HLP objects.</span>
    </a>
    <a href="./specs/contracts#contract-5-ownership-to-handoff">
      <strong>Ownership to handoff</strong>
      <span>Responsibility changes preserve execution correlation.</span>
    </a>
  </div>
</section>

<section class="adoption-strip">
  <h2>Start with the human loop</h2>
  <p>
    Platforms that need accountable harness-backed human-agent work should embed HLP
    directly. Agent harnesses and capability providers stay on their existing
    protocols; HLP only requires narrow adapter contracts at the boundary.
  </p>
  <p><a href="./specs/hlp">Read the HLP spec</a> or <a href="./protocol-map">view the integration map</a>.</p>
</section>
