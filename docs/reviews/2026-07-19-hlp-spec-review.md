# HLP Spec Review — 2026-07-19

Scope: full read of `docs/specs/HLP.md` (982 lines, 0.2.0-draft + appendix C
0.3.0-draft) cross-checked against the reference implementation
(`loops/hlp/`), the conformance suite (`tests/conformance/`), and the
integration contracts. Method: §-by-§ comparison plus mechanical extraction
(operation names, audit action strings, error codes, state transitions).

## Verdict

The spec and the reference implementation are **consistent on all normative
semantics**. Every object schema, state transition, precondition, error code,
integration contract, and appendix-C decision has a matching implementation
anchor, and §8's nine MUSTs all have executable conformance coverage. Three
**documentation-level gaps** were found in the spec's own tables (the
implementation and tests already behaved correctly) and are fixed in this
change. No semantic changes were needed.

## Mechanical cross-checks (all pass)

| Check | Result |
|---|---|
| §4.1 23 operations ↔ `operations.py` public async methods | 23 = 23, 1:1 name mapping |
| §4.2 audit actions ↔ emitted `action="..."` strings | all spec rows emitted; 3 emitted actions were missing from the table (finding 1) |
| §3.3 transitions ↔ `state_machine.py::LEGAL_TRANSITIONS` | exact match; `rejected` missing only from the definition table (finding 2) |
| §6.1 error codes ↔ `types.py::ErrorCode` | 9 = 9 exact |
| §3.2–3.9 schemas ↔ `objects.py` | field-level match (frozen value objects, sealed Review/Artifact, append-only chains) |
| §5.1/§5.2 adapter contracts ↔ `adapters/protocol.py` | 7-method surface present; 2 HLP-event→adapter mappings were undocumented (finding 3) |
| §5.2.1 reliable delivery ↔ `CodexHarnessAdapter` peek/ack + integrated profile cursor tests | match |
| §8 nine MUSTs ↔ `tests/conformance/` | all covered (incl. `state_patch`/`edited_artifact_ref` at compatible:132/170, integrated:60) |
| Appendix C D1–D4 ↔ `realtime.py` + BCI slice + TUI soft buffer | match |
| Version statements ↔ `check_release_metadata.py` guards | pass |

## Findings — fixed in this change

1. **§4.2 audit mapping table incomplete (3 rows added).**
   §4.1 defines 23 operations including `review.comment` and
   `artifact.reference`, and §4.2 states every operation MUST emit its audit
   action — but the table omitted:
   - `review.comment` → `review.commented` (emitted at operations.py:1007)
   - `artifact.reference` → `artifact.referenced` (emitted at operations.py:1099)
   - `task.completed` — side-effect action emitted when a deliverable review
     approval completes the Task (operations.py:972); appendix A's sequence
     relies on it. Added as a side-effect row with a note.

2. **§3.3 state-definition table missing `rejected`.**
   The transition table and `LEGAL_TRANSITIONS` include the `rejected`
   terminal state (`under_review → rejected` on deliverable reject), but the
   state-definition/ownership table listed only 8 states. Added the
   `rejected` row (assignee: principal, terminal).

3. **§5.1 adapter mapping table missing two rows.**
   `AgentAdapter` has 7 methods and the reference lifecycle drives
   `ownership.transfer → handoff` (operations.py:763) and
   `task.cancel → cancel` (operations.py:267), but §5.1 mapped only 6 HLP
   events. Added both rows with their correlation contracts (handoff MUST
   preserve correlation_id across runs; cancel MUST stop the bound run).

## Findings — follow-up (recorded, not changed)

4. **§7 open issues remain genuinely open** (checkpoint timeout default
   §7.2, delegate depth §7.3, ledger concurrency §7.4, multi-reviewer §7.5,
   cross-project artifact refs §7.6, version compatibility §7.7). The
   reference implementation picks documented defaults (e.g. pure suspension
   on interrupt timeout); converging these is spec work for a later draft,
   not this review.
5. **Concurrent checkpoints** (§3.4 SHOULD single pending; appendix C.5
   profile options). The reference store enforces single pending; the
   realtime profile options (Serialize / Scope-partition / Priority stack)
   are documented but only Serialize is exercised. Fine for a draft; revisit
   when a second profile ships.
6. **`risk` vocabularies stay closed sets** (`low|medium|high`). Channel-side
   risk policies (e.g. the BCI demo's keyword/flag example) are
   implementation freedom per §1.2; no spec change needed, noted to avoid
   readers treating the example as a spec-level tier.
