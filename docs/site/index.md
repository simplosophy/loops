---
layout: home

hero:
  name: "Loops"
  text: "Protocol Stack"
  tagline: AI 协作的 OSI 模型 — 三层协议、每层只解一个维度、层间靠显式契约咬合
  actions:
    - theme: brand
      text: 为什么是协议栈
      link: /overview
    - theme: alt
      text: 阅读路线
      link: /reading-routes

features:
  - icon: 🧱
    title: 不重新发明砖
    details: 已有协议（MCP、Skills、A2A、ACP）各自优秀。Loops 给它们一张坐标系和接缝规范，而不是重烧一遍砖。
    link: /specs/cap
    linkText: L0 · CAP
  - icon: 🧩
    title: 填补生态空白
    details: agent↔人 在项目/组织级如何协作，至今无人定义。HACP 就是来补这一格的 — Loops 的核心贡献。
    link: /specs/hacp
    linkText: L2 · HACP
  - icon: 🔌
    title: 显式契约咬合
    details: 三层之间不靠约定，靠契约对象：CapabilityRef、TaskID 贯穿、Checkpoint→Block、Ownership→Handoff。
    link: /specs/contracts
    linkText: 层间契约速查
  - icon: ⬇️
    title: 依赖只能向下
    details: L2→L1→L0。低层永远不知道高层存在。换一层不动另外两层 — 这才是该有的解耦。
    link: /overview
    linkText: 设计原则
---

## 栈全景

<div class="home-stack-art">

<!-- 三层协议栈全景图，移植自 docs/intro.html 的设计语言 -->
<svg viewBox="0 0 720 420" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- 人 (principal) -->
  <rect x="40" y="10" width="640" height="40" rx="20" fill="#8b5cf6" fill-opacity="0.08" stroke="#8b5cf6" stroke-opacity="0.4" stroke-dasharray="4 2"/>
  <text x="360" y="35" text-anchor="middle" fill="#a78bfa" font-size="13" font-weight="600">人 (principal) · 团队成员 · 审批者 · 委派者</text>

  <!-- HACP L2 -->
  <rect x="40" y="70" width="640" height="90" rx="14" fill="#8b5cf6" fill-opacity="0.07" stroke="#8b5cf6" stroke-opacity="0.55"/>
  <rect x="40" y="84" width="4" height="62" rx="2" fill="#8b5cf6"/>
  <rect x="58" y="88" width="56" height="20" rx="5" fill="#8b5cf6"/>
  <text x="86" y="102" text-anchor="middle" fill="#0a0a0f" font-size="11" font-weight="700">L2</text>
  <text x="58" y="128" fill="#a78bfa" font-size="17" font-weight="700">HACP</text>
  <text x="58" y="146" fill="#8a8a9a" font-size="11">人机协作 · Task / Checkpoint / Ownership / Review / Artifact / Ledger / Audit</text>
  <text x="660" y="128" text-anchor="end" fill="#8b5cf6" font-size="10" font-weight="600">★ Loops 新建</text>

  <!-- 协议带 HACP↔AAP -->
  <line x1="40" y1="170" x2="680" y2="170" stroke="#06b6d4" stroke-width="1" stroke-dasharray="5 3" opacity="0.5"/>
  <text x="360" y="184" text-anchor="middle" fill="#06b6d4" font-size="10" opacity="0.8">task.assign / checkpoint.raise↔resolve · TaskID 贯穿</text>

  <!-- AAP L1 -->
  <rect x="40" y="195" width="640" height="80" rx="14" fill="#3b82f6" fill-opacity="0.07" stroke="#3b82f6" stroke-opacity="0.55"/>
  <rect x="40" y="209" width="4" height="52" rx="2" fill="#3b82f6"/>
  <rect x="58" y="213" width="56" height="20" rx="5" fill="#3b82f6"/>
  <text x="86" y="227" text-anchor="middle" fill="#0a0a0f" font-size="11" font-weight="700">L1</text>
  <text x="58" y="253" fill="#60a5fa" font-size="17" font-weight="700">AAP</text>
  <text x="58" y="271" fill="#8a8a9a" font-size="11">agent 间 · delegate / handoff / discovery · 复用 A2A / ACP</text>

  <!-- 协议带 AAP↔CAP -->
  <line x1="40" y1="285" x2="680" y2="285" stroke="#06b6d4" stroke-width="1" stroke-dasharray="5 3" opacity="0.5"/>
  <text x="360" y="299" text-anchor="middle" fill="#06b6d4" font-size="10" opacity="0.8">CapabilityRef (id+version, transport-agnostic)</text>

  <!-- CAP L0 -->
  <rect x="40" y="310" width="640" height="80" rx="14" fill="#f97316" fill-opacity="0.07" stroke="#f97316" stroke-opacity="0.55"/>
  <rect x="40" y="324" width="4" height="52" rx="2" fill="#f97316"/>
  <rect x="58" y="328" width="56" height="20" rx="5" fill="#f97316"/>
  <text x="86" y="342" text-anchor="middle" fill="#0a0a0f" font-size="11" font-weight="700">L0</text>
  <text x="58" y="368" fill="#fb923c" font-size="17" font-weight="700">CAP</text>
  <text x="58" y="386" fill="#8a8a9a" font-size="11">能力 · Tool / Skill · 复用 MCP / Skills</text>

  <!-- 底部标签 -->
  <text x="660" y="368" text-anchor="end" fill="#8a8a9a" font-size="10">依赖只能向下 · 跨层只走契约对象</text>
</svg>

</div>

## 三层协议

<div class="layer-cards">
  <a class="layer-card l2" href="/specs/hacp">
    <h3><span class="badge">L2</span> HACP · 人机协作</h3>
    <p>定义人↔agent 如何围绕 Task 协作。Task / Checkpoint / Ownership / Review / Artifact / Ledger / Audit 七个一等对象。Loops 新建，填补生态空白。</p>
  </a>
  <a class="layer-card l1" href="/specs/aap">
    <h3><span class="badge">L1</span> AAP · agent 间</h3>
    <p>定义 agent↔agent 如何发现、委派、交接。discover / delegate / handoff。复用 A2A / ACP，定义最小接口契约。</p>
  </a>
  <a class="layer-card l0" href="/specs/cap">
    <h3><span class="badge">L0</span> CAP · 能力</h3>
    <p>定义 agent 如何调用外部能力。Tool (单函数) + Skill (打包能力)。复用 MCP / Skills，零改造即可接入。</p>
  </a>
</div>

## 一句话

> loops 协议栈不和 MCP / A2A 竞争，而是给它们一张坐标系。
> **我们把已有协议分层归位，并补上了缺失的人机协作层。**

[开始阅读 →](/overview){.vp-raw}
