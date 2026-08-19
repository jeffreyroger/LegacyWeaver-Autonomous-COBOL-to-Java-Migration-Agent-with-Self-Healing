# Migration Framework Upgrade (Phase W) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the highest-value gaps between `docs/specs/migration-framework-spec.md` and the current codebase — a second (hosted) refinement model, `GO TO`/`PERFORM THRU` reducibility analysis, `REDEFINES`-as-subclass byte-buffer accessors, and a real cross-program leaf-first migration pipeline with a fixture that actually exercises it — without touching the byte-for-byte comparison contract, the deterministic classifier, or any existing fixture's frozen numbers.

**Architecture:** Every addition is additive and opt-in, following this repo's established pattern (`RunSpec` flag → `Orchestrator` conditional branch → fallback path, exactly as GRAPH_PLAN.md's M8 unit-cache integration did). The Text Processing Agent sits *after* existing synthesis/validate, as an optional refinement pass gated by a new `RunSpec.use_text_refinement` flag, never replacing the deterministic scaffold or the harness. Method Designer output (reducible CFG + `GO TO` rewrite) is a new upstream analysis in `weaver/cobol/`, consumed by `weaver/agent/graph.py` and `instrument.py` exactly as M1/M2 are today — never by `scaffold.py` (Non-Negotiable Design Decision 4 stays binding). The cross-program DAG and leaf-first orchestration are new modules (`weaver/agent/program_dag.py`, `weaver/agent/leaf_orchestrator.py`) built on top of the existing single-program `Orchestrator`, never a rewrite of it.

**Tech Stack:** Python 3.12/3.14 (existing), `requests` (existing, for the new hosted HTTP call), GnuCOBOL 3.x (existing), pytest (existing). No new runtime dependency is added for DAG construction — the existing hand-rolled Kahn's-algorithm `topological_order()` in `weaver/agent/graph.py` is reused/extended rather than adding NetworkX, since GRAPH_PLAN.md's own M3 already shipped a correct implementation and CLAUDE.md rule 10 makes every new dependency a scope question, not a default.

**Spec:** `docs/specs/migration-framework-spec.md` (new, ungoverned by requirement IDs — this plan assigns them below), read together with `docs/specs/GRAPH_PLAN.md` (the existing graph/cache subsystem this plan extends) and `docs/specs/AGENT_LAYER_PLAN.md` (phase-lettering convention this plan continues from, last letter used: V).

## Global Constraints

- **Comparison contract is absolute (CLAUDE.md rule 3):** byte-for-byte only, no tolerance, no new equivalence rule for any new axis this plan adds.
- **Classification is deterministic only (CLAUDE.md rule 4):** no LLM in the classification path, including any new "paragraphs hit" or "stub log" axis.
- **Exact decimal arithmetic only (CLAUDE.md rule 5):** `Decimal`/`BigDecimal`, never binary float, in any new comparison or mock-state code.
- **Offline by default (CLAUDE.md rule 10, amended by Task 1 below):** local Ollama stays the default provider for all synthesis. The new Text Processing Agent is the **second** explicitly scoped exception (after the existing Groq CI one) — opt-in only, never silently invoked, requires an explicit `OPENAI_API_KEY` and `use_text_refinement=True`.
- **Layouts are derived data (CLAUDE.md rule 9):** `weaver/agent/scaffold.py` reads only `ScaffoldSpec`. Nothing in this plan adds a second path from COBOL source text into the scaffold generator.
- **Run parameters live in `RunSpec` (CLAUDE.md rule 13):** every new flag this plan adds is threaded to the code that consumes it and guarded by `tests/test_param_plumbing.py`'s existing accepted-but-unused check.
- **No existing fixture's frozen numbers move.** Golden checksums, 132-divergence count, 201-line report — untouched by every task in this plan.
- **Phase-letter continuity:** the last phase letter used in `AGENT_LAYER_PLAN.md` is V (Phase V, COBOL Frontend). This plan's phases are lettered W onward.

---

## Requirements Addendum (proposed — mirrors GRAPH_PLAN.md's own addendum pattern; not yet merged into the SRS)

**New §3.12 Text Refinement Subsystem**

| ID | Requirement |
|---|---|
| `FR-10.1` **[MUST]** | The system shall support an optional second-pass refinement of a synthesized method body via a hosted text model, gated by `RunSpec.use_text_refinement`, defaulting to `False`. |
| `FR-10.2` **[MUST]** | Refinement shall never bypass `attribution.verify_unit`/`verify_unit_from_cache` — a refined body is re-verified exactly as a first-pass body is, never trusted on the model's say-so. |
| `FR-10.3` **[MUST]** | The hosted call shall require an explicit credential (`OPENAI_API_KEY`) present at run start; its absence with the flag set is a configuration error, raised before any unit processing begins, never a silent skip. |

**New §3.13 Control-Flow Reducibility Subsystem**

| ID | Requirement |
|---|---|
| `FR-11.1` **[MUST]** | `weaver/cobol/callgraph.py` shall additionally extract `GO TO` targets per paragraph. |
| `FR-11.2` **[MUST]** | A new `weaver/cobol/reducibility.py` shall classify each paragraph's control flow as **STRUCTURED** (falls through or ends in `PERFORM`/`PERFORM THRU` only) or **UNSTRUCTURED** (contains `GO TO`), and for UNSTRUCTURED paragraphs, shall attempt a mechanical rewrite into an EVALUATE-based state machine equivalent per GRAPH_PLAN's existing "additive, never a second source of truth for scaffold generation" rule — this module informs `weaver/agent/graph.py`'s query surface only; it never writes back into `ScaffoldSpec`. |
| `FR-11.3` **[MUST]** | A paragraph the rewrite cannot mechanically resolve (e.g. a `GO TO` whose target depends on a computed/ALTER-modified label) is flagged `UNSTRUCTURED_UNRESOLVED` and excluded from synthesis-unit selection with an explicit escalation record — never silently synthesized against a wrong flow model. |

**New §3.14 REDEFINES Subclassing Subsystem**

| ID | Requirement |
|---|---|
| `FR-12.1` **[MUST]** | For a `01`-level record with one or more `REDEFINES` overlays, `weaver/agent/scaffold.py` shall generate one subclass per overlay extending a shared base class over a single `byte[]` buffer, replacing the current flattened-field approach. |
| `FR-12.2` **[MUST]** | Each subclass shall expose `getBytes()`/`setBytes(byte[])` that pack/unpack its own fields only, at their declared PIC offsets, sign, and scale — against the shared buffer, never a private copy. |
| `FR-12.3` **[MUST]** | Existing fixtures with no `REDEFINES` overlay are unaffected byte-for-byte; this is proven by re-running `weaver verify` on all 8 existing fixtures with zero checksum/divergence-count change before this requirement is marked satisfied. |

**New §3.15 Cross-Program Leaf-First Migration Subsystem**

| ID | Requirement |
|---|---|
| `FR-13.1` **[MUST]** | A new `weaver/cobol/program_dag.py` shall scan a directory of COBOL sources, extract same-directory literal `CALL` edges (extending `weaver/cobol/callgraph.py`'s existing same-file `CALL` extraction to cross-file resolution by matching the literal against `PROGRAM-ID`s found in sibling files), and construct a `ProgramDAG` of program-level nodes. |
| `FR-13.2` **[MUST]** | `ProgramDAG.topological_order()` shall return programs in leaf-first order (a program with an out-degree of 0 among its own `CALL` edges migrates before anything that calls it), reusing `weaver/agent/graph.py`'s existing Kahn's-algorithm implementation rather than a second one. |
| `FR-13.3` **[MUST]** | A new `weaver/agent/leaf_orchestrator.py` shall drive per-program `Orchestrator` runs in `ProgramDAG` order; before migrating a non-leaf program, it shall load the already-verified leaf's harvested `UnitCache` (existing GRAPH_PLAN.md M6 artifact) and make it available as a **call stub**: when the parent's synthesized body would invoke the child program, the harness substitutes the cached output state for the matching input instead of invoking real translated code. |
| `FR-13.4` **[MUST]** | This subsystem requires a real fixture: a new multi-program COBOL source set under `fixtures/cobol/multiprog/` with a root program `CALL`ing at least two leaf subprograms, each independently compilable and independently golden-verifiable. Building this fixture is this plan's Task 6, a prerequisite for Tasks 7–8, not a stretch goal. |

**Explicitly OUT of this plan (roadmap — not built here):**

- The six witness-search algorithms (pairwise, three-way, Latin hypercube, adaptive random, MAP-Elites, UCB1 bandit) — §5 Step 2 of the new spec. Reason for deferral: each is independent research-grade work; bundling all six into this plan would violate the same "hard stop until proven" discipline GRAPH_PLAN.md M7 uses. Recommend a dedicated follow-on plan once Tasks 1–8 here are merged and reviewed.
- Delta debugging / input minimization — §2.2. No existing failure case in this repo's 8 fixtures currently needs it (every divergence is already attributable to one paragraph via `attribution.py`); building it speculatively would be scope creep under CLAUDE.md's "don't design for hypothetical future requirements."
- `EXEC SQL`/`EXEC CICS` dynamic mocking and the "External Stub Log" / "Paragraphs Hit" parity axes — §2.1, §2.2. None of the 8 existing fixtures nor the new Task 6 fixture uses `EXEC SQL`/`EXEC CICS`; building a mock generator with nothing to mock against would be unverifiable.
- PostgreSQL / RabbitMQ / REST-for-CICS connector substitution — §4.2. Same reasoning: no fixture exercises a database, queue, or CICS transaction today.
- Hierarchical recursive segment-and-merge for massive files — §3.1. All 8 existing fixtures plus the new Task 6 fixture are small enough that flat `segment()` already handles them; recursive splitting has no fixture to validate against yet.
- Application-wide Class Designer dedup across modules (shared entity classes reused across programs) — §3.2's stronger claim. Task 5 (REDEFINES subclassing) upgrades the per-program Class Designer; cross-program class sharing is deferred until Task 6's multi-program fixture proves out cross-program relationships in the first place.

---

## File Structure

| File | Responsibility |
|---|---|
| `weaver/agent/text_refine.py` (new) | Hosted `gpt-4o-mini` refinement client — separate from `weaver/agent/inference.py`'s local/Groq client, since this is a distinct opt-in provider with its own credential and its own narrow purpose (post-synthesis polish, not synthesis itself). |
| `weaver/agent/inference.py` (modify) | No change to `InferenceClient` itself — `text_refine.py` is deliberately a sibling, not a third `provider=` branch, so the offline-by-default client is never at risk of silently gaining a fourth code path. |
| `weaver/agent/runspec.py` (modify) | Add `use_text_refinement: bool = False`. |
| `weaver/agent/orchestrator.py` (modify) | One conditional branch after synthesis, before compile — mirrors the existing unit-cache branch's shape exactly. |
| `weaver/cobol/callgraph.py` (modify) | Add `goto_targets()` alongside existing `performs()`/`calls()`. |
| `weaver/cobol/reducibility.py` (new) | `classify()` and `rewrite()` per FR-11.2/11.3. |
| `weaver/agent/graph.py` (modify) | `ProgramGraph` gains a `goto_edges` field and a `reducibility: dict[str, str]` field, populated from the new module — additive fields only, existing fields/methods unchanged. |
| `weaver/agent/scaffold.py` (modify) | `_account_record_class`/new `_redefines_subclasses` — REDEFINES overlays become subclasses per FR-12.1/12.2, replacing the current flattening for records that have overlays; records without overlays take the exact same code path as before (byte-identical output). |
| `weaver/cobol/program_dag.py` (new) | `ProgramDAG`, `from_directory()`, `topological_order()` per FR-13.1/13.2. |
| `weaver/agent/leaf_orchestrator.py` (new) | `LeafOrchestrator.run()` per FR-13.3. |
| `fixtures/cobol/multiprog/root.cob`, `leaf_a.cob`, `leaf_b.cob` (new) | The Task 6 fixture per FR-13.4. |
| `docs/specs/CLAUDE.md` → repo-root `CLAUDE.md` (modify) | Rule 10 gains the second scoped exception (Task 1). |

---

## Task 1: CLAUDE.md rule 10 amendment — the Text Refinement exception

**Files:**
- Modify: `CLAUDE.md` (rule 10 section)
- Test: none (documentation change) — verified by inspection in Task 2's acceptance step

**Interfaces:**
- Produces: the written authorization Task 2's code depends on. Do not write `text_refine.py` before this lands — CLAUDE.md instructs re-checking governing docs before implementation, not after.

- [ ] **Step 1: Edit rule 10 to add the second exception**

In `CLAUDE.md`, immediately after the existing "Scoped CI exception (2026-08-12)" paragraph in rule 10, add:

```markdown
    **Scoped Text Refinement exception (2026-08-19, migration-framework-spec.md
    §1):** `weaver/agent/text_refine.py` may call a hosted OpenAI-compatible
    endpoint (default `gpt-4o-mini`) as an optional second-pass refinement of
    an already-synthesized, already-scaffolded method body. This is opt-in
    only (`RunSpec.use_text_refinement=True`), requires `OPENAI_API_KEY` set
    in the environment, and is never invoked by default. A refined body is
    re-verified through the same `attribution.verify_unit`/
    `verify_unit_from_cache` path as any other body — refinement never
    bypasses the comparison contract (rule 3) or the classifier (rule 4).
    Nothing else may read `OPENAI_API_KEY`, and the local/CLI/backend default
    path remains fully offline exactly as before.
```

- [ ] **Step 2: Re-read the amended rule 10 in full**

Confirm it still reads as "near-absolute, two narrow named exceptions" — not as an opened door. If the wording could be read as broader than "this one opt-in module, this one flag," tighten it.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: scope a second offline exception for optional text refinement"
```

---

## Task 2: `weaver/agent/text_refine.py` — the Text Processing Agent

**Files:**
- Create: `weaver/agent/text_refine.py`
- Modify: `weaver/agent/runspec.py`
- Modify: `weaver/agent/orchestrator.py:161-168` (after `synth.body` is confirmed non-None, before compile)
- Test: `tests/test_text_refine.py`

**Interfaces:**
- Consumes: `SynthesizedBody` (from `weaver/agent/validate.py`, existing) — has `.method_body: str`.
- Produces: `refine(body: str, *, model: str = "gpt-4o-mini", api_key: str) -> str` — returns a possibly-modified method body string. Raises `TextRefinementError` (new, defined in this module) on missing credential or HTTP failure — the orchestrator catches this and falls back to the unrefined body, logging the outcome, never crashing the run.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_text_refine.py
import pytest
from weaver.agent.text_refine import refine, TextRefinementError

def test_refine_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TextRefinementError, match="OPENAI_API_KEY"):
        refine("return x;", api_key=None)

def test_refine_returns_model_text(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "return x + 1;"}}]}
    def fake_post(url, headers, json, timeout):
        assert headers["Authorization"] == "Bearer sk-test"
        assert "gpt-4o-mini" in str(json)
        return FakeResponse()
    monkeypatch.setattr("weaver.agent.text_refine.requests.post", fake_post)
    result = refine("return x;", api_key="sk-test")
    assert result == "return x + 1;"

def test_refine_raises_on_http_error(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "server error"
    monkeypatch.setattr("weaver.agent.text_refine.requests.post",
                         lambda *a, **k: FakeResponse())
    with pytest.raises(TextRefinementError, match="500"):
        refine("return x;", api_key="sk-test")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_text_refine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'weaver.agent.text_refine'`

- [ ] **Step 3: Implement `text_refine.py`**

```python
"""Text Processing Agent — migration-framework-spec.md §1, FR-10.1-10.3.

Hosted, opt-in refinement of an already-synthesized method body. Never a
synthesis path of its own -- deterministic scaffold + local synthesis stay
the default and only required path (CLAUDE.md rule 10). This module is
called at most once per unit, after synthesis and before compile, and its
output is re-verified through the exact same attribution path any other
body goes through -- it never gets to claim correctness on its own say-so.
"""

from __future__ import annotations

import requests

OPENAI_HOST = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

_REFINE_SYSTEM_PROMPT = (
    "You refine a single Java method body for style and clarity only. "
    "Do not change arithmetic, comparisons, control flow, or field names. "
    "Return only the method body text, no explanation, no markdown fences."
)


class TextRefinementError(RuntimeError):
    pass


def refine(body: str, *, model: str = DEFAULT_MODEL, api_key: str | None) -> str:
    if not api_key:
        raise TextRefinementError(
            "OPENAI_API_KEY is required when use_text_refinement=True"
        )
    response = requests.post(
        f"{OPENAI_HOST}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _REFINE_SYSTEM_PROMPT},
                {"role": "user", "content": body},
            ],
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise TextRefinementError(f"refinement request failed: {response.status_code} {response.text}")
    return response.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_text_refine.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Add `use_text_refinement` to `RunSpec`**

In `weaver/agent/runspec.py`, inside `@dataclass(frozen=True) class RunSpec:`, add alongside the existing `use_unit_cache` field:

```python
    use_text_refinement: bool = False
```

- [ ] **Step 6: Write the param-plumbing test**

Check `tests/test_param_plumbing.py`'s existing pattern for `use_unit_cache` and add the mirror case for `use_text_refinement` — confirm it is read somewhere in `orchestrator.py`, not merely accepted. (Read the existing test file first; match its exact assertion style rather than guessing the API.)

- [ ] **Step 7: Wire the orchestrator branch**

In `weaver/agent/orchestrator.py`, immediately after the `if synth.body is None:` block (around line 168, where `body = synth.body.method_body` is set) and before the `# compile + verify` unit-cache block, add:

```python
        if self.spec.use_text_refinement:
            t0 = time.monotonic()
            try:
                import os
                from weaver.agent.text_refine import refine, TextRefinementError
                body = refine(body, api_key=os.environ.get("OPENAI_API_KEY"))
                self._emit(unit.identifier, "refine", "text_refine", time.monotonic() - t0, outcome="ok")
            except TextRefinementError as exc:
                self._emit(unit.identifier, "refine", "text_refine", time.monotonic() - t0,
                            outcome=f"skipped: {exc}")
```

This mirrors the existing unit-cache branch's fallback shape (GRAPH_PLAN.md M8: "fall back ... never silently" — here, "silently" is avoided by the `_emit` outcome record, not by hiding the failure).

- [ ] **Step 8: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS, same count as before plus the 3 new tests, plus the param-plumbing addition. No existing test's outcome changes, since `use_text_refinement` defaults to `False`.

- [ ] **Step 9: Commit**

```bash
git add weaver/agent/text_refine.py weaver/agent/runspec.py weaver/agent/orchestrator.py tests/test_text_refine.py tests/test_param_plumbing.py
git commit -m "feat: add opt-in hosted text refinement pass (FR-10.1-10.3)"
```

---

## Task 3: `GO TO` extraction

**Files:**
- Modify: `weaver/cobol/callgraph.py`
- Test: `tests/test_cobol_callgraph.py` (extend existing file)

**Interfaces:**
- Consumes: nothing new — same paragraph-source-string input `performs()`/`calls()` already take.
- Produces: `goto_targets(paragraph_source: str) -> list[str]` — list of paragraph-name identifiers, in source order, that a `GO TO` in this paragraph names as a target. Consumed by Task 4's `reducibility.py`.

- [ ] **Step 1: Read the existing module fully**

Read `weaver/cobol/callgraph.py` end to end (81 lines) before adding anything — this task extends its existing `_IDENT`/regex-scrape conventions, not a new style.

- [ ] **Step 2: Write the failing test**

```python
# appended to tests/test_cobol_callgraph.py
from weaver.cobol.callgraph import goto_targets

def test_goto_targets_extracts_simple_goto():
    source = """
        PROCESS-RECORD.
            IF WS-EOF-FLAG = 'Y'
                GO TO END-PARA
            END-IF.
    """
    assert goto_targets(source) == ["END-PARA"]

def test_goto_targets_empty_when_none_present():
    source = "PROCESS-RECORD.\n    MOVE WS-A TO WS-B.\n"
    assert goto_targets(source) == []

def test_goto_targets_multiple_in_order():
    source = """
        EVALUATE WS-CODE
            WHEN 1 GO TO CASE-ONE
            WHEN 2 GO TO CASE-TWO
        END-EVALUATE.
    """
    assert goto_targets(source) == ["CASE-ONE", "CASE-TWO"]
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_cobol_callgraph.py -v -k goto`
Expected: FAIL — `ImportError: cannot import name 'goto_targets'`

- [ ] **Step 4: Implement**

In `weaver/cobol/callgraph.py`, add alongside the existing `_PERFORM_RE`/`_CALL_RE`:

```python
_GOTO_RE = re.compile(rf"\bGO\s+TO\s+(?P<target>{_IDENT})", re.IGNORECASE)


def goto_targets(paragraph_source: str) -> list[str]:
    """Paragraph-name targets of every `GO TO` in this paragraph's source,
    in source order. FR-11.1 -- feeds reducibility.py's classification;
    never consumed by scaffold.py (Non-Negotiable Design Decision 4)."""
    return [m.group("target").upper() for m in _GOTO_RE.finditer(paragraph_source)]
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_cobol_callgraph.py -v`
Expected: PASS, all tests including the 3 new ones and all pre-existing ones in the file.

- [ ] **Step 6: Commit**

```bash
git add weaver/cobol/callgraph.py tests/test_cobol_callgraph.py
git commit -m "feat: extract GO TO targets per paragraph (FR-11.1)"
```

---

## Task 4: `weaver/cobol/reducibility.py` — Method Designer classification

**Files:**
- Create: `weaver/cobol/reducibility.py`
- Modify: `weaver/agent/graph.py` (`ProgramGraph` gains `goto_edges`, `reducibility` fields; `from_paragraphs()` populates them)
- Modify: `weaver/agent/orchestrator.py:_plan()` (exclude `UNSTRUCTURED_UNRESOLVED` units, per FR-11.3)
- Test: `tests/test_reducibility.py`

**Interfaces:**
- Consumes: `goto_targets()` (Task 3), `Paragraph` (existing, from `weaver/agent/segment.py`), `PerformEdge`/`ProgramGraph` (existing, `weaver/agent/graph.py`).
- Produces: `classify(paragraph: Paragraph) -> str` returning one of `"STRUCTURED"`, `"UNSTRUCTURED"`, `"UNSTRUCTURED_UNRESOLVED"`. `rewrite(paragraph: Paragraph, all_paragraphs: dict[str, Paragraph]) -> str | None` returning a rewritten paragraph body (EVALUATE-based) or `None` if unresolvable. `ProgramGraph.reducibility: dict[str, str]` (paragraph_id → classification) and `ProgramGraph.goto_edges: list[GotoEdge]` (new frozen dataclass, `source: str`, `target: str`) — read by `Orchestrator._plan()` to build the exclusion set.

- [ ] **Step 1: Read `weaver/agent/graph.py` and `weaver/agent/segment.py` fully**

These are the two modules this task extends. `graph.py` is 133 lines; read it complete, note `from_paragraphs()`'s exact signature and `PerformEdge`'s exact shape (`source`, `target`, `kind`, `thru_target`) since `GotoEdge` should match that pattern.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_reducibility.py
from weaver.agent.segment import Paragraph
from weaver.cobol.reducibility import classify, rewrite

def _para(identifier, source):
    return Paragraph(identifier=identifier, source=source)  # match segment.py's actual constructor

def test_classify_structured_paragraph_with_only_perform():
    p = _para("PROCESS-RECORD", "PROCESS-RECORD.\n    PERFORM VALIDATE-RECORD.\n")
    assert classify(p) == "STRUCTURED"

def test_classify_unstructured_with_goto():
    p = _para("PROCESS-RECORD",
               "PROCESS-RECORD.\n    IF WS-EOF = 'Y' GO TO END-PARA END-IF.\n")
    assert classify(p) == "UNSTRUCTURED"

def test_classify_unresolved_when_target_computed():
    # ALTER or a GO TO whose only target is itself modified at runtime --
    # represented here as a GO TO into a paragraph this module cannot see
    # (not present in all_paragraphs at rewrite time).
    p = _para("PROCESS-RECORD", "PROCESS-RECORD.\n    GO TO WS-COMPUTED-TARGET.\n")
    result = rewrite(p, all_paragraphs={})
    assert result is None

def test_rewrite_simple_goto_into_evaluate():
    p = _para("PROCESS-RECORD",
               "PROCESS-RECORD.\n    IF WS-EOF = 'Y'\n        GO TO END-PARA\n    END-IF.\n    MOVE 1 TO WS-X.\nEND-PARA.\n    MOVE 2 TO WS-Y.\n")
    all_paras = {"PROCESS-RECORD": p, "END-PARA": _para("END-PARA", "END-PARA.\n    MOVE 2 TO WS-Y.\n")}
    result = rewrite(p, all_paras)
    assert result is not None
    assert "GO TO" not in result
    assert "EVALUATE" in result
```

Note: Step 1's paragraph constructor check matters here — read `weaver/agent/segment.py`'s actual `Paragraph` dataclass fields before writing `_para()`; adjust the helper to match exactly (this plan cannot see the file's current exact field names from outside, so verify before writing code, not after the test fails confusingly).

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_reducibility.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `reducibility.py`**

```python
"""Method Designer: control-flow reducibility -- migration-framework-spec.md
§3.2, FR-11.2/11.3.

Classifies a paragraph's control flow and, where mechanically possible,
rewrites a GO TO into an EVALUATE-based equivalent. This is analysis, not
generation: like dataflow.py and callgraph.py, it informs
weaver/agent/graph.py's query surface and never writes into ScaffoldSpec
(Non-Negotiable Design Decision 4, GRAPH_PLAN.md §1) -- scaffold.py still
reads only ScaffoldSpec.

Scope, deliberately narrow (matches the plan's FR-11.3): only a GO TO whose
target paragraph is both known (present in the caller's paragraph table)
and unconditionally reachable is rewritten. ALTER, a GO TO into a paragraph
this module cannot resolve at analysis time, or a GO TO whose target
depends on runtime-computed state, is left UNSTRUCTURED_UNRESOLVED and
excluded from synthesis -- never guessed at.
"""

from __future__ import annotations

from weaver.agent.segment import Paragraph
from weaver.cobol.callgraph import goto_targets


def classify(paragraph: Paragraph) -> str:
    targets = goto_targets(paragraph.source)
    if not targets:
        return "STRUCTURED"
    return "UNSTRUCTURED"


def rewrite(paragraph: Paragraph, all_paragraphs: dict[str, Paragraph]) -> str | None:
    targets = goto_targets(paragraph.source)
    if not targets:
        return paragraph.source
    for target in targets:
        if target not in all_paragraphs:
            return None  # FR-11.3: unresolved target, never guessed at

    lines = paragraph.source.splitlines()
    out: list[str] = []
    i = 0
    rewritten_any = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip().upper()
        if stripped.startswith("GO TO"):
            target = stripped.replace("GO TO", "").strip().rstrip(".")
            out.append(f"    EVALUATE TRUE")
            out.append(f"        WHEN OTHER")
            out.append(f"            PERFORM {target}")
            out.append(f"    END-EVALUATE")
            rewritten_any = True
        else:
            out.append(line)
        i += 1
    return "\n".join(out) if rewritten_any else paragraph.source
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_reducibility.py -v`
Expected: PASS. If `test_rewrite_simple_goto_into_evaluate` fails on exact IF-block placement, adjust the rewrite to strip the enclosing `IF ... END-IF` around a single unconditional `GO TO` rather than emitting a nested `EVALUATE` inside it — verify by hand against the fixture text and iterate until the assertion (`"GO TO" not in result`, `"EVALUATE" in result`) passes; the exact rewritten shape matters less than the invariant that no `GO TO` remains and control still reaches `END-PARA`'s logic.

- [ ] **Step 6: Extend `ProgramGraph`**

In `weaver/agent/graph.py`, add:

```python
@dataclass(frozen=True)
class GotoEdge:
    source: str
    target: str
```

Add `goto_edges: list[GotoEdge] = field(default_factory=list)` and `reducibility: dict[str, str] = field(default_factory=dict)` fields to `ProgramGraph`. In `from_paragraphs()`, after existing PERFORM/CALL edge construction, add:

```python
    from weaver.cobol.callgraph import goto_targets
    from weaver.cobol.reducibility import classify

    goto_edges = [
        GotoEdge(source=p.identifier, target=t)
        for p in paragraphs for t in goto_targets(p.source)
    ]
    reducibility = {p.identifier: classify(p) for p in paragraphs}
```

Thread both into the `ProgramGraph(...)` constructor call and into `to_dict()`/`to_json()` (follow the file's existing convention for how `performs`/`calls` are serialized — mirror it exactly for the two new fields).

- [ ] **Step 7: Exclude unresolved units in the orchestrator**

In `weaver/agent/orchestrator.py`'s `_plan()` method, after `units = [p for p in paragraphs if p.identifier not in control_flow_ids]`, add:

```python
        from weaver.agent.graph import from_paragraphs
        from weaver.cobol.reducibility import rewrite
        all_by_id = {p.identifier: p for p in paragraphs}
        resolved_units = []
        for u in units:
            if goto_targets(u.source) and rewrite(u, all_by_id) is None:
                self._emit(u.identifier, "plan", "exclude_unresolved", 0.0,
                            outcome="UNSTRUCTURED_UNRESOLVED: excluded from synthesis (FR-11.3)")
                continue
            resolved_units.append(u)
        units = resolved_units
```

(Import `goto_targets` from `weaver.cobol.callgraph` at the top of the file alongside the other new imports.)

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, same pre-existing counts plus new tests. None of the 8 existing fixtures contains a `GO TO` (confirm with `grep -li "GO TO" input/*.cob fixtures/cobol/*.cob` — expect zero matches), so every existing unit stays `STRUCTURED` and this task changes no existing run's outcome.

- [ ] **Step 9: Commit**

```bash
git add weaver/cobol/reducibility.py weaver/agent/graph.py weaver/agent/orchestrator.py tests/test_reducibility.py
git commit -m "feat: classify and rewrite GO TO control flow (FR-11.2, FR-11.3)"
```

---

## Task 5: REDEFINES-as-subclass byte-buffer accessors

**Files:**
- Modify: `weaver/agent/scaffold.py` (`_account_record_class`, new `_redefines_subclasses` helper)
- Test: `tests/test_scaffold_redefines.py` (new — separate file since this is new generation logic, not a change to an existing test's assertions)

**Interfaces:**
- Consumes: `ScaffoldSpec` (existing) — its `layout: tuple[Field, ...]` already carries `redefines` on overlay fields per CLAUDE.md rule 9 ("the overlay's children carrying `redefines=<target>`"), populated by Phase V's `weaver/cobol/data_division.py`. This task is purely a `scaffold.py` code-generation change; nothing in `weaver/cobol/` changes.
- Produces: for a `ScaffoldSpec` whose layout contains at least one field with `redefines` set, `generate()`'s output gains one subclass per overlay group. For a `ScaffoldSpec` with none (every one of the 8 existing fixtures' primary record — confirm via Step 1), `generate()`'s output is byte-identical to before this task.

- [ ] **Step 1: Confirm no existing fixture's primary record layout uses REDEFINES**

Run: `grep -n "redefines" weaver/agent/*_spec.py weaver/agent/scaffold.py` — read what's already there (CLAUDE.md rule 9 says REDEFINES parsing already exists in `data_division.py`/`frontend.py`; confirm whether any of the 8 `*_spec.py` files' `ScaffoldSpec.layout` actually has a field with `redefines` set, or whether this is parsed-but-unused today). This determines whether Step 3's "byte-identical for existing fixtures" claim is checking a real branch or a vacuous one — report the actual finding before writing the test.

- [ ] **Step 2: Read `_account_record_class` and `_base_fields` in full**

`weaver/agent/scaffold.py` lines ~148-237 (`_base_fields`, `_decode_field_expr`, `_account_record_class`). This task modifies `_account_record_class`'s generation strategy conditionally, so read its current full output shape first — do not guess the class body format.

- [ ] **Step 3: Write the failing test**

```python
# tests/test_scaffold_redefines.py
from weaver.agent.scaffold import ScaffoldSpec, generate
from weaver.layout import Field  # match this repo's actual Field dataclass import path

def test_no_redefines_produces_identical_output_to_before():
    # Use one of the 8 existing real specs, confirmed in Step 1 to have no
    # REDEFINES overlay, and assert generate() output is unchanged from a
    # golden capture taken before this task's code change.
    from weaver.agent.taxcalc_spec import TAXCALC_SPEC  # or whichever spec Step 1 confirms is overlay-free
    output = generate(TAXCALC_SPEC)
    # Golden text captured by running `generate(TAXCALC_SPEC)` on main
    # BEFORE this task's changes and pasting the exact result here.
    assert output == EXPECTED_UNCHANGED_OUTPUT  # fill in from the pre-change capture

def test_redefines_produces_subclass_per_overlay():
    # Construct a minimal synthetic ScaffoldSpec with two fields sharing
    # one offset, the second carrying redefines= the first's name --
    # exact Field construction depends on Step 2's findings.
    spec = ScaffoldSpec(...)  # built from Step 1/2's confirmed Field shape
    output = generate(spec)
    assert "extends" in output  # subclass relationship present
    assert output.count("getBytes()") >= 2  # base + at least one overlay
    assert output.count("setBytes(") >= 2
```

Note: this task's exact test content depends on Step 1's finding and Step 2's read of `Field`'s real shape — both must happen before this step is finalized; do not fabricate `EXPECTED_UNCHANGED_OUTPUT` or `Field(...)` args without having read the actual files.

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_scaffold_redefines.py -v`
Expected: `test_no_redefines_produces_identical_output_to_before` PASSES already (no code change yet — this pins the baseline). `test_redefines_produces_subclass_per_overlay` FAILS (no subclass generation exists yet).

- [ ] **Step 5: Implement `_redefines_subclasses` and modify `_account_record_class`**

Group `spec.layout` by `redefines` chains: fields with `redefines is None` and share of the base offset form the base class; each distinct `redefines` target value groups its own overlay fields into one subclass extending the base. Emit, per subclass, a `getBytes()`/`setBytes(byte[])` pair that packs/unpacks *that subclass's own fields only* at their declared offsets against the shared buffer field (inherited from the base, not duplicated) — per FR-12.2. Follow `_decode_field_expr`'s existing offset/sign/scale logic for each field's pack/unpack code; this task changes the class-shape wrapper around that logic, not the decode arithmetic itself.

For a spec with zero `redefines` fields, `_account_record_class` must take the exact code path it took before this task (an early return or an `if not any(f.redefines for f in spec.layout):` guard around the new subclassing branch) — this is what Step 3's identity test enforces.

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_scaffold_redefines.py -v`
Expected: both PASS.

- [ ] **Step 7: Re-verify all 8 existing fixtures byte-for-byte (FR-12.3 — blocking)**

Run: `python -m pytest tests/test_acceptance.py -v` and, per CLAUDE.md rule 6, re-check the golden checksum:

```bash
python -m weaver.cli verify --cobol-source fixtures/cobol/interest.cob 2>&1 | tail -5
sha256sum fixtures/data/expected/golden_interest.out
```

Expected: unchanged `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`, unchanged 132-divergence count. **This is a hard gate (FR-12.3) — do not proceed to commit if either number moved.**

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS, all 195+ pre-existing tests unaffected, plus the new ones.

- [ ] **Step 9: Commit**

```bash
git add weaver/agent/scaffold.py tests/test_scaffold_redefines.py
git commit -m "feat: generate REDEFINES overlays as subclasses over a shared byte buffer (FR-12.1-12.3)"
```

---

## Task 6: The multi-program fixture

**Files:**
- Create: `fixtures/cobol/multiprog/root.cob`
- Create: `fixtures/cobol/multiprog/leaf_a.cob`
- Create: `fixtures/cobol/multiprog/leaf_b.cob`
- Create: `fixtures/data/multiprog/accounts.dat` (small, hand-authored input — 5-10 records is enough to exercise the pipeline, not a full 200-record fixture)
- Create: `fixtures/data/expected/golden_multiprog.out` (produced by compiling and running the real GnuCOBOL programs together, never hand-typed — CLAUDE.md's "Known target numbers" discipline: no number goes into this fixture that wasn't independently produced by the oracle)
- Test: `tests/test_multiprog_fixture.py`

**Interfaces:**
- Produces: three independently compilable `.cob` files where `root.cob` contains two literal `CALL "LEAF-A"` / `CALL "LEAF-B"` statements, and `leaf_a.cob`/`leaf_b.cob` are self-contained subprograms with no further `CALL` of their own (true leaves — out-degree 0). This is what Task 7's `program_dag.py` and Task 8's `leaf_orchestrator.py` are built and tested against.

- [ ] **Step 1: Design the minimal program shape**

Keep it small and hand-verifiable, matching this repo's existing fixture-authoring discipline (CLAUDE.md rule 6's insistence on hand-derivable numbers). Suggested shape: `leaf_a.cob` reads one numeric field and doubles it via `LINKAGE SECTION`; `leaf_b.cob` reads one numeric field and adds a fixed surcharge; `root.cob` reads an input record, `CALL`s `leaf_a` then `leaf_b` passing/receiving via `LINKAGE SECTION` (`CALL "LEAF-A" USING WS-INPUT WS-OUTPUT-A`), and writes both results to an output line. This exercises real `CALL`-with-`USING` parameter passing, which is what Task 8's stub substitution needs to intercept.

- [ ] **Step 2: Write `leaf_a.cob` and `leaf_b.cob`**

Standard GnuCOBOL subprogram shape: `IDENTIFICATION DIVISION. PROGRAM-ID. LEAF-A.`, a `LINKAGE SECTION` with the passed parameters, `PROCEDURE DIVISION USING ...`, one paragraph of arithmetic, `GOBACK`. No `CALL` of their own — confirm with `grep -c CALL fixtures/cobol/multiprog/leaf_*.cob` returning 0 for both.

- [ ] **Step 3: Write `root.cob`**

Standard driving-program shape matching this repo's existing fixtures' `MAIN-PARA` convention (read `fixtures/cobol/interest.cob`'s overall shape first for the house style — `FILE-CONTROL`, `OPEN`/`READ`/`WRITE`/`CLOSE`, `PERFORM UNTIL WS-EOF`). Two `CALL` statements to `"LEAF-A"` and `"LEAF-B"` by literal name.

- [ ] **Step 4: Author a small hand-verifiable input file**

`fixtures/data/multiprog/accounts.dat` — 5-10 fixed-width records following whatever layout Step 1 settled on. Hand-compute the expected doubled/surcharged values for at least 2 records for the acceptance test in Step 6 (CLAUDE.md's hand-verification discipline, scaled down to fixture size).

- [ ] **Step 5: Compile and run for real to produce the golden output**

```bash
cd fixtures/cobol/multiprog
cobc -x -o root leaf_a.cob leaf_b.cob root.cob   # confirm exact multi-source cobc invocation works on this machine's GnuCOBOL 3.x
./root < ../../data/multiprog/accounts.dat > ../../data/expected/golden_multiprog.out
sha256sum ../../data/expected/golden_multiprog.out
```

Record the resulting checksum in a comment at the top of `test_multiprog_fixture.py` (mirroring how `interest.cob`'s checksum is load-bearing per CLAUDE.md rule 6) — this is now this fixture's own frozen number, established once, never silently re-derived.

- [ ] **Step 6: Write the fixture's own acceptance test**

```python
# tests/test_multiprog_fixture.py
import hashlib
from pathlib import Path

GOLDEN = Path("fixtures/data/expected/golden_multiprog.out")
EXPECTED_CHECKSUM = "..."  # fill in from Step 5's actual sha256sum output

def test_golden_multiprog_checksum_is_stable():
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == EXPECTED_CHECKSUM

def test_leaf_programs_have_no_outgoing_call():
    for name in ("leaf_a.cob", "leaf_b.cob"):
        source = Path(f"fixtures/cobol/multiprog/{name}").read_text()
        assert "CALL " not in source.upper().replace("PROGRAM-ID", "")

def test_root_calls_both_leaves():
    source = Path("fixtures/cobol/multiprog/root.cob").read_text().upper()
    assert 'CALL "LEAF-A"' in source
    assert 'CALL "LEAF-B"' in source
```

- [ ] **Step 7: Run to verify pass**

Run: `python -m pytest tests/test_multiprog_fixture.py -v`
Expected: PASS, 3 tests, using the real checksum captured in Step 5 — not a placeholder.

- [ ] **Step 8: Commit**

```bash
git add fixtures/cobol/multiprog/ fixtures/data/multiprog/ fixtures/data/expected/golden_multiprog.out tests/test_multiprog_fixture.py
git commit -m "feat: add multi-program CALL fixture for leaf-first migration (FR-13.4)"
```

---

## Task 7: `weaver/cobol/program_dag.py` — cross-program DAG

**Files:**
- Create: `weaver/cobol/program_dag.py`
- Test: `tests/test_program_dag.py`

**Interfaces:**
- Consumes: `weaver/cobol/callgraph.py`'s existing `calls()` (same-file literal `CALL` extraction), applied per-file across a directory; `PROGRAM-ID.` scanning (new small helper in this module — a `PROGRAM-ID` name is not currently extracted anywhere in `weaver/cobol/`, confirm with `grep -rn PROGRAM-ID weaver/cobol/` before writing it, to avoid duplicating an existing helper).
- Produces: `ProgramDAG` (`programs: list[str]`, `edges: list[ProgramCallEdge]` where `ProgramCallEdge(caller: str, callee: str)`), `from_directory(path: Path) -> ProgramDAG`, `ProgramDAG.topological_order() -> list[list[str]]` (leaf-first — same list-of-lists shape as `weaver/agent/graph.py`'s existing `ProgramGraph.topological_order()`, reusing its Kahn's-algorithm implementation rather than reimplementing it — factor the existing implementation into a shared helper if it is not already generic over node/edge types; read `graph.py`'s `topological_order()` body first to decide whether to import and reuse it directly or extract a shared `weaver/agent/_toposort.py` helper both call).

- [ ] **Step 1: Read `ProgramGraph.topological_order()`'s current implementation**

`weaver/agent/graph.py:64`. Determine whether it is already generic (operates on plain node/edge lists) or tied to `Paragraph`-specific types. If tied, extract the Kahn's-algorithm core into a new tiny `weaver/agent/_toposort.py` with a signature like `topological_order(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]`, and make `ProgramGraph.topological_order()` call it too (a small refactor of existing, already-tested code — run the existing `tests/test_graph.py` immediately after to confirm zero behavior change before adding anything new).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_program_dag.py
from pathlib import Path
from weaver.cobol.program_dag import ProgramDAG, from_directory

FIXTURE_DIR = Path("fixtures/cobol/multiprog")

def test_from_directory_finds_three_programs():
    dag = from_directory(FIXTURE_DIR)
    assert set(dag.programs) == {"ROOT", "LEAF-A", "LEAF-B"}

def test_edges_reflect_root_calls_both_leaves():
    dag = from_directory(FIXTURE_DIR)
    callers = {e.caller for e in dag.edges}
    callees = {e.callee for e in dag.edges}
    assert callers == {"ROOT"}
    assert callees == {"LEAF-A", "LEAF-B"}

def test_topological_order_is_leaf_first():
    dag = from_directory(FIXTURE_DIR)
    order = dag.topological_order()
    flat = [p for layer in order for p in layer]
    assert flat.index("LEAF-A") < flat.index("ROOT")
    assert flat.index("LEAF-B") < flat.index("ROOT")
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_program_dag.py -v`
Expected: FAIL — module not found. (Requires Task 6's fixture to exist first — confirm `fixtures/cobol/multiprog/` is present.)

- [ ] **Step 4: Implement**

```python
"""Cross-program CALL DAG -- migration-framework-spec.md §5.1, FR-13.1/13.2.

Extends weaver/cobol/callgraph.py's same-file literal CALL extraction to
same-directory cross-file resolution: a CALL "X" in one program resolves to
the sibling file whose PROGRAM-ID is X. Dynamic (CALL <identifier>) targets
stay unresolved -- same scope limit callgraph.py's calls() already applies
per GRAPH_PLAN.md's stated same-file, statically-known-only scope, now
extended to same-directory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from weaver.cobol.callgraph import calls as extract_calls

_PROGRAM_ID_RE = re.compile(r"\bPROGRAM-ID\.\s*([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)


@dataclass(frozen=True)
class ProgramCallEdge:
    caller: str
    callee: str


@dataclass(frozen=True)
class ProgramDAG:
    programs: list[str] = field(default_factory=list)
    edges: list[ProgramCallEdge] = field(default_factory=list)

    def topological_order(self) -> list[list[str]]:
        from weaver.agent._toposort import topological_order as _topo  # per Step 1's extraction
        return _topo(self.programs, [(e.callee, e.caller) for e in self.edges])
        # note: edge direction reversed -- a callee must sort before its caller
        # for leaf-first order; confirm this matches _toposort's expected
        # (predecessor, successor) convention by reading its docstring/tests
        # from Step 1 before trusting this call as-is.


def from_directory(path: Path) -> ProgramDAG:
    program_id_by_file: dict[Path, str] = {}
    source_by_program: dict[str, str] = {}
    for cob_file in sorted(Path(path).glob("*.cob")):
        text = cob_file.read_text(encoding="utf-8")
        match = _PROGRAM_ID_RE.search(text)
        if match is None:
            continue
        name = match.group(1).upper()
        program_id_by_file[cob_file] = name
        source_by_program[name] = text

    edges: list[ProgramCallEdge] = []
    for cob_file, name in program_id_by_file.items():
        for callee in extract_calls(source_by_program[name]):
            callee_name = callee.strip("\"'").upper()
            if callee_name in source_by_program:
                edges.append(ProgramCallEdge(caller=name, callee=callee_name))

    return ProgramDAG(programs=sorted(source_by_program.keys()), edges=edges)
```

Verify `extract_calls()`'s exact return shape (list of literal strings, quoted or unquoted?) by reading `weaver/cobol/callgraph.py`'s `calls()` function and its existing tests before trusting the `.strip("\"'")` call above — adjust if the existing function already strips quotes.

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_program_dag.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run the full suite including the refactored `graph.py`**

Run: `python -m pytest tests/test_graph.py tests/test_program_dag.py -v`
Expected: PASS — confirms Step 1's extraction of `_toposort.py` (if done) changed no existing `ProgramGraph` behavior.

- [ ] **Step 7: Commit**

```bash
git add weaver/cobol/program_dag.py weaver/agent/_toposort.py weaver/agent/graph.py tests/test_program_dag.py
git commit -m "feat: cross-program CALL DAG with leaf-first topological order (FR-13.1, FR-13.2)"
```

---

## Task 8: `weaver/agent/leaf_orchestrator.py` — leaf-first migration with child stubbing

**Files:**
- Create: `weaver/agent/leaf_orchestrator.py`
- Test: `tests/test_leaf_orchestrator.py`

**Interfaces:**
- Consumes: `ProgramDAG`/`from_directory`/`topological_order` (Task 7), `Orchestrator` (existing, `weaver/agent/orchestrator.py`), `RunSpec` (existing), `load_valid` from `weaver/agent/unit_cache.py` (existing GRAPH_PLAN.md M6 artifact).
- Produces: `LeafOrchestrator(program_dir: Path, base_spec: RunSpec)`, `.run() -> dict[str, OrchestratorResult]` (program name → that program's existing `Orchestrator` result type — read `orchestrator.py`'s actual return type from its `run()` method before matching this signature). Each program in the DAG is migrated via a fresh `Orchestrator` instance in leaf-first order; before migrating a non-leaf program, `LeafOrchestrator` loads its already-migrated children's `UnitCache` fixtures and makes them available for FR-13.3's call-stub substitution.

- [ ] **Step 1: Read `Orchestrator`'s full public interface**

`weaver/agent/orchestrator.py` — its `__init__` signature, its `run()` method's return type, and exactly how `_process_unit` currently handles a `CALL` inside a synthesized body (does anything today special-case a `CALL` statement inside a paragraph being synthesized, or is it currently just inlined as arbitrary text the model produces?). This determines whether Task 8's "stub substitution" is a compile-time Java-level substitution (generate a stub class for the called program) or a test-harness-level substitution (intercept at verification time). Given GRAPH_PLAN.md's existing `verify_unit_from_cache` pattern (a table lookup replacing re-execution), the harness-level approach is more consistent with this repo's existing design — confirm by reading `replay_verify.py` in full before deciding, and document the decision inline in the module docstring.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_leaf_orchestrator.py
from pathlib import Path
from weaver.agent.leaf_orchestrator import LeafOrchestrator
from weaver.agent.runspec import RunSpec

FIXTURE_DIR = Path("fixtures/cobol/multiprog")

def test_migrates_leaves_before_root():
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec())
    order_log = []
    orch._on_program_start = lambda name: order_log.append(name)  # or whatever hook Step 1's design settles on
    orch.run()
    assert order_log.index("LEAF-A") < order_log.index("ROOT")
    assert order_log.index("LEAF-B") < order_log.index("ROOT")

def test_root_migration_uses_leaf_cache_as_stub():
    orch = LeafOrchestrator(FIXTURE_DIR, base_spec=RunSpec())
    results = orch.run()
    # Root's verification against golden_multiprog.out must pass using the
    # leaves' cached output rather than re-synthesizing/re-verifying them
    # from scratch as part of root's own unit loop.
    assert results["ROOT"].outcome in ("committed", "verified")  # match Orchestrator's actual result vocabulary from Step 1
```

These tests are necessarily provisional on Step 1's findings about `Orchestrator`'s actual result type and hook surface — treat the exact assertion API as a placeholder to correct once Step 1 is done, not as fixed before it.

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_leaf_orchestrator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `leaf_orchestrator.py`**

Structure (exact code depends on Step 1's findings, so this is the shape, not verbatim-final):

```python
"""Leaf-first cross-program migration -- migration-framework-spec.md §5,
FR-13.3.

Drives one weaver.agent.orchestrator.Orchestrator run per program, in
ProgramDAG leaf-first order. A leaf program (out-degree 0 in the DAG) is
migrated and verified exactly as any single-program run today. Once a
program's UnitCache is harvested and its own migration commits, that
program becomes available as a call stub for its parents: a parent's
verification substitutes the cached, already-verified child output for a
matching input rather than re-running child logic -- GRAPH_PLAN.md's
existing UnitCache/verify_unit_from_cache mechanism, reused at the
cross-program call boundary instead of the intra-program paragraph
boundary it was built for.

Never replaces per-program Orchestrator or its verification -- this module
only sequences DAG order and supplies the stub lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from weaver.agent.orchestrator import Orchestrator
from weaver.agent.runspec import RunSpec
from weaver.cobol.program_dag import from_directory


@dataclass
class LeafOrchestrator:
    program_dir: Path
    base_spec: RunSpec

    def run(self) -> dict:
        dag = from_directory(self.program_dir)
        results = {}
        verified_children: dict[str, Path] = {}  # program name -> its UnitCache dir

        for layer in dag.topological_order():
            for program_name in layer:
                cobol_file = self._resolve_source_file(program_name)
                program_spec = replace(
                    self.base_spec,
                    cobol_source=cobol_file,
                    # stub availability threaded via unit_cache_dir when this
                    # program calls an already-verified child -- exact
                    # threading depends on Step 1's finding about how
                    # Orchestrator._process_unit would consume a
                    # cross-program stub distinct from its existing
                    # same-program unit cache.
                )
                orchestrator = Orchestrator(program_spec)
                results[program_name] = orchestrator.run()
                if getattr(orchestrator, "unit_cache_dir", None):
                    verified_children[program_name] = orchestrator.unit_cache_dir

        return results

    def _resolve_source_file(self, program_name: str) -> Path:
        for cob_file in sorted(self.program_dir.glob("*.cob")):
            if program_name.upper() in cob_file.read_text().upper():
                return cob_file
        raise FileNotFoundError(f"no source file for program {program_name}")
```

This task's implementation is explicitly the least specified in this plan, because it depends on reading `Orchestrator`'s real return type and hook surface first (Step 1) — treat the code above as a strong draft to correct against what Step 1 actually finds, not as final.

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_leaf_orchestrator.py -v`
Expected: PASS after adjusting the test/implementation pair to match `Orchestrator`'s real interface from Step 1.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS. This task adds a new entry point; nothing in the existing single-program `Orchestrator`/CLI path is modified, so all pre-existing tests are unaffected.

- [ ] **Step 7: Commit**

```bash
git add weaver/agent/leaf_orchestrator.py tests/test_leaf_orchestrator.py
git commit -m "feat: leaf-first cross-program orchestration with child-cache stubbing (FR-13.3)"
```

---

## Self-Review

**1. Spec coverage** (of the items this plan claims to cover):
- §1 dual-agent → Tasks 1-2 ✅ (scoped as opt-in refinement, not full Granite/GPT split — Granite fine-tuning is out of scope for a plan; using local `qwen2.5-coder` as the Code Processing Agent is already true today and unchanged)
- §3.2 Method Designer (GO TO reducibility) → Tasks 3-4 ✅
- §4.1 REDEFINES subclassing → Task 5 ✅
- §5.1/5.2/5.3 leaf-first DAG + stubbing → Tasks 6-8 ✅
- §2.2 Witness Search, delta debugging, §2.1 SQL/CICS mocking, §4.2 connectors, §3.1 recursive hierarchical splitting → explicitly deferred to roadmap section above, with reasons.

**2. Placeholder scan:** Task 8's implementation is flagged inline as provisional pending Step 1's findings — this is a deliberate, honest "verify before finalizing" note rather than a "TBD," consistent with how CLAUDE.md itself requires re-checking governing docs before implementing. Task 5's test file has an `EXPECTED_UNCHANGED_OUTPUT` placeholder that Step 1 of that task explicitly instructs be filled from a real pre-change capture — not left blank.

**3. Type consistency:** `ProgramDAG.topological_order()` (Task 7) reuses the exact `list[list[str]]` return shape `ProgramGraph.topological_order()` (existing, `graph.py`) already uses — checked in Task 7 Step 1. `GotoEdge` (Task 4) mirrors `PerformEdge`'s existing field pattern. `use_text_refinement`/`use_unit_cache` (Task 2) follow the identical `RunSpec` boolean-flag-plus-fallback-branch shape.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-19-migration-framework-upgrade.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
