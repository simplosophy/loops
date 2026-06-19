---
layout: home

hero:
  name: Loops
  text: Protocol Stack
  tagline: "A layered coordination model for AI systems: humans assign and review work, agents delegate work, and runtimes invoke capabilities through explicit contracts."
  image:
    src: /logo.svg
    alt: Loops protocol mark
  actions:
    - theme: brand
      text: Read the Overview
      link: /overview
    - theme: alt
      text: View the Protocol Map
      link: /protocol-map
---

<section class="protocol-brief">
  <p class="eyebrow">Version 0.1.0-draft</p>
  <h2>Loops is not another agent framework. It is a protocol stack for coordination.</h2>
  <p>
    Existing systems already define important parts of the AI stack: tools, skills,
    and agent-to-agent delegation. Loops gives those pieces a stable layered model
    and adds the missing top layer for human-agent work.
  </p>
</section>

<section class="stack-diagram" aria-label="Loops three-layer protocol stack">
  <img class="stack-art" src="./assets/stack.svg" alt="Loops Protocol Stack diagram: HACP above AAP above CAP, joined by explicit inter-layer contracts.">
  <p class="stack-caption">Three layers, four contracts. HACP is newly defined by Loops; AAP and CAP profile protocols that already exist.</p>
</section>

<section class="route-cards" aria-label="Primary reading routes">
  <a class="route-card" href="./overview">
    <strong>Understand the model</strong>
    <span>Read the protocol positioning, design principles, and layer responsibilities.</span>
  </a>
  <a class="route-card" href="./protocol-map">
    <strong>Map the stack</strong>
    <span>See ownership, operations, identity, and contract boundaries in one place.</span>
  </a>
  <a class="route-card" href="./reading-routes">
    <strong>Start implementing</strong>
    <span>Choose the right path for capability providers, agent runtimes, or platforms.</span>
  </a>
  <a class="route-card" href="./conformance">
    <strong>Check compatibility</strong>
    <span>Validate CAP, AAP, HACP, and full-stack conformance claims.</span>
  </a>
</section>

<section class="layer-cards" aria-label="Protocol layers">
  <a class="layer-card l2" href="./specs/hacp">
    <span class="badge">L2</span>
    <h3>HACP</h3>
    <p>Defines how people assign, gate, review, and govern work performed by autonomous agents.</p>
  </a>
  <a class="layer-card l1" href="./specs/aap">
    <span class="badge">L1</span>
    <h3>AAP</h3>
    <p>Defines the minimum conformance profile for agent discovery, delegation, blocking, and handoff.</p>
  </a>
  <a class="layer-card l0" href="./specs/cap">
    <span class="badge">L0</span>
    <h3>CAP</h3>
    <p>Defines the capability interface that lets agents invoke tools and packaged skills without transport leakage.</p>
  </a>
</section>

<section class="protocol-grid">
  <article>
    <h2>What Loops standardizes</h2>
    <ul>
      <li>Human-agent work units with stable task identity.</li>
      <li>Decision checkpoints that pause agent work until a human resolves them.</li>
      <li>Reviewable artifacts with immutable versions and provenance.</li>
      <li>Audit trails that can replay every protocol operation.</li>
      <li>Layer contracts that keep implementation details from crossing boundaries.</li>
    </ul>
  </article>
  <article>
    <h2>What Loops does not replace</h2>
    <ul>
      <li>MCP servers and Skills runtimes remain the natural L0 implementations.</li>
      <li>A2A, ACP, and agent meshes remain natural L1 implementations.</li>
      <li>Host platforms still choose transport, persistence, identity, RBAC, and UI.</li>
      <li>Agent runtimes remain free to choose models, prompts, tools, and execution loops.</li>
    </ul>
  </article>
</section>

<section class="adoption-strip">
  <h2>Adopt one layer at a time</h2>
  <p>
    Capability providers can start with CAP. Agent runtimes can expose the AAP
    profile. Platforms that need accountable human-agent collaboration can implement
    HACP directly and bridge downward through the explicit contracts.
  </p>
  <p><a href="./protocol-map">Use the protocol map</a> or <a href="./conformance">view conformance requirements</a>.</p>
</section>
