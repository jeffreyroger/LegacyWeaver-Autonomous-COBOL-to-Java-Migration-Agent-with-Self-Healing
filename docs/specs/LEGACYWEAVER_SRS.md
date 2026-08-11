# Software Requirements Specification
## LegacyWeaver — Autonomous COBOL-to-Java Migration Agent with Differential Verification and Self-Healing

| Field | Value |
|---|---|
| Version | 1.0 |
| Date | 07 August 2026 |
| Project | PRISM Hackathon 2026 — Theme 1: Autonomous AI Agents for Real-World Impact |
| Institution | Chennai Institute of Technology |
| Status | Draft for submission |
| Document standard | Adapted from IEEE Std 830-1998 |

---

# 1. Introduction

## 1.1 Purpose

This document specifies the functional and non-functional requirements for **LegacyWeaver**, an autonomous software agent that migrates COBOL batch programs to Java and — critically — **proves the migration semantically correct by executing both versions and comparing their outputs**, repairing its own output when they diverge.

It is intended for the development team, the PRISM evaluation panel, and any future contributor.

## 1.2 Product Scope

LegacyWeaver addresses the central failure mode of legacy modernisation: not that translation is impossible, but that **nobody can prove the translation is correct**. Business rules in COBOL are undocumented and implicitly encoded in data layouts and arithmetic conventions. A translation that compiles and runs may still be silently wrong — and in financial systems, silently wrong means money is lost on every transaction until someone notices.

LegacyWeaver's insight is that the legacy system contains its own specification: **the compiled COBOL binary is a perfect, freely available oracle.** Any candidate Java translation can be validated by running both against identical inputs and comparing outputs byte-for-byte. Every mismatch is a defect with a concrete reproducer, obtained without a human reviewer and without a written spec.

**Every component executes on local hardware. The system performs no network egress at runtime.** This is a hard architectural requirement (§3.6.1), motivated by the fact that the source code LegacyWeaver processes — core banking logic — cannot lawfully or contractually be transmitted to third-party inference providers by its owners.

## 1.3 Definitions, Acronyms and Abbreviations

| Term | Definition |
|---|---|
| **Copybook** | A reusable COBOL data-layout definition, included via `COPY`. Defines field names, types, byte widths. |
| **PIC / PICTURE clause** | COBOL type declaration. `PIC S9(9)V99` = signed, 9 integer digits, implied decimal, 2 fraction digits. |
| **Implied decimal (`V`)** | A decimal point that exists logically but occupies no byte in storage. A major source of 100× errors. |
| **COMP-3** | Packed decimal. Two digits per byte, sign in the low nibble of the last byte. |
| **REDEFINES** | Declares a second field occupying the *same bytes* as an earlier one. |
| **88-level** | A condition name attached to a field, encoding a named business condition. |
| **Paragraph** | The smallest named, callable unit of COBOL procedural code. LegacyWeaver's unit of migration. |
| **Migration Unit (MU)** | One COBOL paragraph plus its resolved data context; the atomic work item. |
| **Oracle** | The compiled original COBOL program, used as ground truth. |
| **Differential execution** | Running the COBOL oracle and the candidate Java against identical input and diffing results. |
| **Divergence** | Any observable difference between oracle and candidate output. |
| **Defect Class** | A categorisation of divergence that determines repair strategy. |
| **Repair cycle** | One iteration of diagnose → patch → re-verify. |
| **Failure Memory** | Persistent, searchable store of past divergences and their verified patches. |
| **Scaffold** | Java code generated deterministically from the copybook, without model inference. |
| **SLM** | Small Language Model — a locally-executed model, ≤32B parameters, quantised. |
| **GBNF** | Grammar-constrained decoding format used by llama.cpp to force structurally valid output. |
| **HITL** | Human-in-the-loop. |

## 1.4 References

| ID | Reference |
|---|---|
| R1 | GnuCOBOL — open-source COBOL compiler. Used as the oracle runtime. |
| R2 | ProLeap COBOL Parser — ANTLR4 grammar producing AST and Abstract Semantic Graph; passes the NIST COBOL-85 test suite. *(Optional dependency, see §3.5.3)* |
| R3 | COBOLEval (Bloop AI, 2024) — first COBOL benchmark for LLMs; establishes that frontier models perform poorly on COBOL. |
| R4 | IEEE Std 830-1998 — Recommended Practice for Software Requirements Specifications. |
| R5 | llama.cpp / Ollama — local inference runtimes for quantised GGUF models. |
| R6 | PRISM Hackathon Theme 1 brief and evaluation criteria. |

## 1.5 Overview

Section 2 describes the product context, its users, and its constraints. Section 3 states the detailed requirements. Section 4 defines the data model. Section 5 gives acceptance criteria. Appendices cover the local model configuration and the demonstration fixture.

---

# 2. Overall Description

## 2.1 Product Perspective

LegacyWeaver is a **self-contained, offline command-line agent**. It is not a service, not a plugin, and has no cloud component. It consumes COBOL source and sample data from the local filesystem and produces Java source, a verification report, and an execution trace.

```
                        ┌─────────────────────────────────┐
                        │        DEVELOPER MACHINE        │
                        │        (no network egress)      │
                        │                                 │
  COBOL source ────────▶│  ┌───────────────────────────┐  │────▶ Java source
  Copybooks    ────────▶│  │      LegacyWeaver         │  │────▶ Verification report
  Sample data  ────────▶│  │      Orchestrator         │  │────▶ Execution trace
                        │  └─────────┬─────────────────┘  │────▶ Escalation cards
                        │            │                    │
                        │   ┌────────┼────────┐           │
                        │   ▼        ▼        ▼           │
                        │ llama.cpp Docker  SQLite+       │
                        │ (local)  (sandbox) FAISS        │
                        └─────────────────────────────────┘
```

### 2.1.1 Rationale for local-only inference

| Driver | Consequence |
|---|---|
| **Regulatory** | Core banking source code is subject to data-localisation and third-party-disclosure restrictions. Cloud inference is prohibited by the intended users' own policy. |
| **Commercial** | Migration engagements process millions of lines. Per-token cloud pricing makes iterative repair loops economically irrational; local inference has zero marginal cost per token, which is precisely what a retry-heavy architecture requires. |
| **Architectural honesty** | If the system's correctness depended on a frontier model, the contribution would be the model, not the system. Constraining inference to a 7B local model forces the *harness* to carry the correctness burden — which is the actual thesis. |
| **Demonstrability** | Network egress can be disabled during evaluation and the system continues to function, which is directly verifiable by the panel. |

### 2.1.2 Consequence: the model does less work

Small local models are weak at COBOL — [R3] establishes that even frontier models solve only a small fraction of COBOL tasks. LegacyWeaver therefore **minimises the surface area delegated to inference**:

| Concern | Produced by | Why |
|---|---|---|
| Field decoders, byte offsets, scaling | **Deterministic code generation** from parsed PIC clauses | Fully specified by the copybook; inference would only add risk |
| Java class skeleton, I/O loop, record reader | **Templates** | Structurally identical across all programs |
| Test vector generation | **Deterministic**, from FieldSpec domains | Rule-driven |
| Divergence classification | **Deterministic** rules over numeric/string diffs | Signals are unambiguous |
| Padding, scale, sign repairs | **Deterministic patchers** | Mechanical corrections |
| Arithmetic and control-flow body of a paragraph | **Local SLM** | Genuinely requires semantic interpretation |
| Root-cause narration for escalation | **Local SLM** | Natural-language summarisation |

Roughly **80% of emitted Java is deterministic.** The model translates short, isolated paragraph bodies into Java — a far easier task than generating COBOL, and one where a 7B coder model is adequate.

## 2.2 Product Functions

| # | Function |
|---|---|
| F1 | Parse COBOL source and copybooks into paragraphs and typed field specifications |
| F2 | Build a dependency graph over paragraphs and derive a migration order |
| F3 | Deterministically generate Java scaffolding from field specifications |
| F4 | Synthesise Java method bodies for each paragraph using a local model |
| F5 | Generate boundary-aware test vectors from field domains |
| F6 | Execute COBOL oracle and Java candidate in isolated containers against identical input |
| F7 | Diff outputs and classify any divergence into a defect class |
| F8 | Retrieve prior verified patches from failure memory |
| F9 | Repair the candidate and re-verify, up to a bounded attempt limit |
| F10 | Escalate unresolved defects to a human with a full diagnostic record |
| F11 | Persist every state transition as a structured trace and compute metrics |
| F12 | Replay a cached run deterministically for demonstration |

## 2.3 User Classes and Characteristics

| Class | Description | Needs |
|---|---|---|
| **Migration Engineer** (primary) | Java developer, limited COBOL knowledge, tasked with modernising a legacy system | Correct Java; clear reporting of what could not be verified |
| **Legacy SME** (secondary) | Long-tenured COBOL developer; scarce, expensive, near retirement | To be consulted only on genuinely ambiguous logic — never on mechanical detail |
| **Evaluator** (PRISM panel) | Assesses agentic behaviour and technical depth | Visible reasoning, live verification, honest failure handling |

## 2.4 Operating Environment

| Component | Requirement |
|---|---|
| OS | Linux (Ubuntu 22.04+) or macOS; Windows via WSL2 |
| Python | 3.11+ |
| Container runtime | Docker Engine 24+ |
| Oracle runtime | GnuCOBOL 3.x (containerised) |
| Candidate runtime | OpenJDK 21 (containerised) |
| Inference runtime | llama.cpp server or Ollama, bound to `127.0.0.1` |
| RAM | 16 GB minimum |
| VRAM | 8 GB recommended; CPU-only supported in degraded mode (§3.4.4) |
| Disk | 25 GB (model weights, containers, run artefacts) |
| Network | **None required at runtime.** Required once, for initial setup. |

## 2.5 Design and Implementation Constraints

| ID | Constraint |
|---|---|
| C1 | **No outbound network calls during a migration run.** Enforced by test (§5.3) and by container network policy. |
| C2 | No proprietary or licence-restricted components. All dependencies MIT / Apache-2.0 / GPL-compatible. |
| C3 | All generated and executed code runs inside containers with no network, read-only root filesystem, and CPU/wall-clock limits. |
| C4 | Model inference must be reproducible: temperature 0, fixed seed, pinned model digest. |
| C5 | Correctness determinations are made **only** by byte comparison of program output. No model is permitted to judge correctness. |
| C6 | Scope is limited to sequential-file COBOL batch programs. CICS, DB2, IMS and VSAM are explicitly excluded. |
| C7 | Delivery deadline 12 August 2026 constrains implementation to the requirements marked **[MUST]**. |

## 2.6 Assumptions and Dependencies

| ID | Assumption |
|---|---|
| A1 | Input COBOL compiles under GnuCOBOL without modification. |
| A2 | Programs are deterministic — identical input yields identical output. No wall-clock, RNG, or external state dependence. |
| A3 | Representative input data is available or can be synthesised from field specifications. |
| A4 | Programs are single-compilation-unit; no inter-program `CALL`. |
| A5 | The user's machine can run a 7B quantised model at ≥10 tokens/second, or accepts degraded mode. |

---

# 3. Specific Requirements

Priority: **[MUST]** required for the 12 Aug demonstration · **[SHOULD]** build if schedule permits · **[COULD]** roadmap only.

## 3.1 Perception Subsystem

### FR-1.1 Source ingestion **[MUST]**
The system shall accept a COBOL source file and zero or more copybook files, resolve `COPY` statements by textual substitution, and produce a single expanded source unit. Fixed-format (columns 8–72) and free-format shall both be accepted; format shall be auto-detected from the first 100 non-comment lines.

### FR-1.2 Paragraph segmentation **[MUST]**
The system shall partition the `PROCEDURE DIVISION` into paragraphs. A paragraph header is a non-comment line beginning in Area A (columns 8–11) consisting of a label terminated by a period. Each paragraph shall be assigned a stable identifier, source line range, and verbatim text.

### FR-1.3 Field specification extraction **[MUST]**
For every data item in the `FILE SECTION`, `WORKING-STORAGE SECTION` and resolved copybooks, the system shall derive a `FieldSpec` (§4.1) containing: level number, name, PIC string, USAGE, byte offset within its 01-group, byte width, numeric scale, sign presence, sign encoding, parent, and `REDEFINES` target.

Byte offsets shall be computed by walking the level hierarchy. `REDEFINES` items shall be assigned the offset of their target, **not** appended.

### FR-1.4 Condition-name resolution **[MUST]**
88-level items shall be attached to their parent field with their value set, and made available as named boolean predicates during synthesis.

### FR-1.5 Data-flow analysis **[SHOULD]**
For each paragraph the system shall determine the set of fields read and the set written, by matching identifiers against the FieldSpec table. This set constitutes the paragraph's data context.

*Degraded behaviour:* if unavailable, the full FieldSpec table is supplied as context. Costs prompt tokens; does not affect correctness.

### FR-1.6 Semantic graph extraction **[COULD]**
Where the ProLeap parser [R2] is available, the system shall use its ASG for control- and data-flow rather than the heuristics in FR-1.2/1.5. **This requirement is optional by design and shall be abandoned if not operational by 2026-08-09T23:00 IST.**

## 3.2 Planning Subsystem

### FR-2.1 Dependency graph **[MUST]**
The system shall construct a directed graph with paragraphs as nodes and edges for (a) `PERFORM` invocations and (b) shared mutable field access (writer → reader).

### FR-2.2 Migration ordering **[MUST]**
The system shall emit a topological ordering of the graph, leaf-first. Cycles shall be collapsed into a single composite Migration Unit and flagged.

### FR-2.3 Plan exposure **[MUST]**
The plan shall be persisted as JSON and rendered in the CLI before execution, showing each unit's identifier, dependencies, and status. The plan shall be visible to the operator *before* any code is generated.

## 3.3 Synthesis Subsystem

### FR-3.1 Deterministic scaffold generation **[MUST]**
From the FieldSpec table alone, and **without model inference**, the system shall generate:

- a Java `record` per 01-level group, with `BigDecimal` for numerics at the PIC-implied scale;
- a fixed-width record decoder using computed byte offsets;
- decoders for zoned decimal (including sign-overpunch) and, where present, COMP-3;
- a fixed-width encoder honouring PIC edit masks (`-9(9).99` etc.);
- the main record-iteration loop and file I/O;
- a JUnit harness stub per Migration Unit.

Scaffold output shall be byte-identical across runs for identical input.

### FR-3.2 Body synthesis **[MUST]**
For each Migration Unit the system shall invoke the local model with: the paragraph source, the FieldSpecs in its data context, applicable condition names, and the target method signature. The model shall return only a method body.

Constraints:
- temperature 0, fixed seed
- output constrained to a JSON schema via GBNF grammar or equivalent
- context ≤ 4096 tokens per call
- **prohibited:** declaring new fields, altering the scaffold, introducing `double` or `float`, calling undeclared helpers

### FR-3.3 Response validation **[MUST]**
Model output shall be validated before use: JSON well-formedness, schema conformance, and a static check rejecting `double`, `float`, `Math.round`, and unqualified division on `BigDecimal`. Validation failure triggers immediate regeneration (max 2), then classification as `SYNTHESIS_FAILURE`.

### FR-3.4 Assumption capture **[MUST]**
The model shall additionally return a list of assumptions made. Assumptions shall be recorded and surfaced in escalation cards.

### FR-3.5 Compilation **[MUST]**
Assembled Java shall be compiled with `javac` inside the sandbox. Compilation errors shall enter the repair loop as defect class `COMPILE_ERROR`.

## 3.4 Verification Subsystem

### FR-4.1 Test vector generation **[MUST]**
For each input FieldSpec the system shall generate vectors covering: zero; minimum and maximum representable; negative maximum (signed only); all-spaces and low-values (alphanumeric only); PIC-width boundary; and **arithmetic truncation boundaries** — values whose computed result falls immediately above a truncation cut point.

Vectors shall be deterministic given a seed. Default: 200 records.

### FR-4.2 Oracle execution **[MUST]**
The system shall compile the original COBOL with GnuCOBOL and execute it in a container against the vector set, capturing stdout, stderr, all output files, and exit code.

### FR-4.3 Candidate execution **[MUST]**
The system shall execute the candidate Java in a separate container against byte-identical input, capturing the same artefacts.

### FR-4.4 Differential comparison **[MUST]**
Outputs shall be compared byte-for-byte after normalising line endings only. **No other normalisation is permitted** — trailing whitespace differences are genuine defects.

The comparison shall emit a `DivergenceReport` (§4.4) identifying, for the first and every subsequent divergence: record index, byte offset, field name (resolved via FieldSpec offsets), oracle value, candidate value, and numeric delta where applicable.

### FR-4.5 Equivalence determination **[MUST]**
A Migration Unit is *verified* if and only if divergence count is zero across all vectors and both exit codes match. No other criterion — human, heuristic, or model-based — shall mark a unit verified.

## 3.5 Diagnosis and Repair Subsystem

### FR-5.1 Defect classification **[MUST]**
Divergences shall be classified deterministically:

| Class | Signal | Repair |
|---|---|---|
| `TRUNCATION` | numeric, \|Δ\| < 1 ULP at field scale | apply `setScale(n, RoundingMode.DOWN)`; strip float arithmetic |
| `SCALE` | \|Δ\| ratio ≈ 10^k | recompute implied-decimal scaling from PIC `V` position |
| `SIGN` | equal magnitude, opposite sign | correct sign-nibble / overpunch decode |
| `PADDING` | equal after `strip()`, unequal raw | re-emit through PIC edit mask |
| `CONTROL_FLOW` | record count differs, or field absent | regenerate body with explicit condition table |
| `COMPILE_ERROR` | javac non-zero | supply compiler diagnostics to synthesis |
| `SYNTHESIS_FAILURE` | invalid model output ×3 | escalate immediately |

### FR-5.2 Deterministic repair **[MUST]**
`PADDING`, `SCALE` and `SIGN` shall be repaired by rule-based patchers **without model inference**. This is a correctness requirement, not an optimisation: these corrections are fully determined by the FieldSpec.

### FR-5.3 Model-assisted repair **[MUST]**
`TRUNCATION`, `CONTROL_FLOW` and `COMPILE_ERROR` shall invoke the local model with a strategy-specific prompt containing the failing input record, both outputs, the byte offset, the current method, and the classification.

### FR-5.4 Attempt bounding **[MUST]**
Repair attempts per Migration Unit shall be capped at **K = 3** (configurable). Each attempt's patch shall be hashed; a repeated hash terminates the loop immediately and escalates, rather than consuming the remaining budget.

### FR-5.5 Regression guard **[MUST]**
After any repair, the full vector set shall be re-run. A patch that fixes the reported divergence but increases total divergence count shall be reverted and recorded as a failed attempt.

## 3.6 Failure Memory Subsystem

### FR-6.1 Local embedding **[MUST]**
Symptom signatures shall be embedded using a **locally executed** embedding model. No embedding API shall be used.

### FR-6.2 Storage **[MUST]**
Failure cases (§4.6) shall be persisted in a local file-backed vector index (FAISS or Chroma) plus SQLite metadata. The store shall survive process restart.

### FR-6.3 Retrieval-first repair **[MUST]**
Before any model inference, the repair subsystem shall query memory with the symptom signature and normalised COBOL construct. On cosine similarity ≥ 0.85, the stored patch shall be applied and verified **with zero model calls**. On verification failure, the loop falls through to FR-5.3 and the retrieved case's confidence is decremented.

### FR-6.4 Write-back **[MUST]**
Every verified repair shall be written to memory with symptom signature, defect class, normalised construct, root cause, patch diff, and verification status.

### FR-6.5 Cost accounting **[MUST]**
The system shall record model calls per resolved defect, and report memory hit rate, so that cost reduction across runs is measurable rather than asserted.

## 3.7 Human-in-the-Loop Subsystem

### FR-7.1 Escalation trigger **[MUST]**
On exhausting K attempts, on repeated patch hash, or on `SYNTHESIS_FAILURE`, the unit shall be marked `ESCALATED` and migration shall continue with remaining independent units.

### FR-7.2 Escalation card **[MUST]**
Each escalation shall produce a record containing: unit identifier; failing input record; oracle and candidate values with delta; defect class and confidence; **every attempt made, the patch applied, and why it failed**; suspected COBOL source lines; and assumptions recorded under FR-3.4.

### FR-7.3 Operator decision **[SHOULD]**
The operator shall be able to accept, reject, or supply a replacement body. Accepted decisions shall be verified per FR-4.5 and written to memory per FR-6.4.

## 3.8 Observability

### FR-8.1 Structured trace **[MUST]**
Every state transition shall append a `TraceEvent` (§4.7) to `runs/<run_id>/trace.jsonl`: timestamp, unit, node, action, duration, model calls consumed, outcome.

### FR-8.2 Metrics **[MUST]**
On completion the system shall report: pre- and post-repair semantic equivalence rate; mean repair iterations; autonomous resolution rate; model calls per defect; memory hit rate; total wall-clock and inference time.

### FR-8.3 Baseline comparison **[MUST]**
The system shall support a `--baseline` mode performing single-shot whole-program translation with no verification or repair, evaluated against the same vectors. This quantifies the harness's contribution independently of the model's.

### FR-8.4 Replay **[MUST]**
All model interactions shall be cached keyed by prompt hash. `--replay` shall serve exclusively from cache, guaranteeing a deterministic, inference-free demonstration.

## 3.9 External Interfaces

### 3.9.1 Command-line interface **[MUST]**
```
weaver migrate  <program.cbl> [--copybook DIR] [--data FILE] [--out DIR]
                [--max-repairs 3] [--model qwen2.5-coder:7b] [--seed 42]
weaver verify   --cobol <src> --java <src> --data <file>
weaver baseline <program.cbl>
weaver replay   <run_id>
weaver memory   list | export | import <file>
weaver report   <run_id>
```

### 3.9.2 Local inference interface **[MUST]**
The system shall communicate with the inference runtime over HTTP restricted to `127.0.0.1`. The endpoint shall be configurable. **The configured host shall be validated as loopback at startup; a non-loopback host shall cause the run to abort.**

### 3.9.3 Sandbox interface **[MUST]**
Containers shall be launched with `--network=none`, `--read-only` (except a writable `/out` tmpfs), `--memory=2g`, `--cpus=2`, and a 30-second wall-clock kill.

### 3.9.4 Terminal UI **[MUST]** / Web trace UI **[SHOULD]**
The CLI shall stream unit status with colour coding. A browser-based trace view is desirable but explicitly non-essential and shall be the first component cut under schedule pressure.

---

## 3.10 Non-Functional Requirements

### 3.10.1 Performance

| ID | Requirement |
|---|---|
| NFR-P1 | Perception of a 500-line program shall complete in ≤ 5 s |
| NFR-P2 | One differential verification cycle (200 vectors, both runtimes) shall complete in ≤ 20 s |
| NFR-P3 | One body synthesis call shall complete in ≤ 45 s on the reference GPU configuration (App. A, Tier 1) |
| NFR-P4 | End-to-end migration of the demonstration fixture shall complete in ≤ 12 min without replay, ≤ 60 s with `--replay` |
| NFR-P5 | A memory-hit repair shall complete in ≤ 5 s (no inference) |

### 3.10.2 Reliability

| ID | Requirement |
|---|---|
| NFR-R1 | Failure of one Migration Unit shall not prevent migration of independent units |
| NFR-R2 | Run state shall be checkpointed per unit and resumable after interruption |
| NFR-R3 | Inference runtime unavailability shall degrade to deterministic-repair-only mode with a clear warning, not a crash |
| NFR-R4 | No repair loop shall be unbounded; K and wall-clock caps are both enforced |

### 3.10.3 Security and Isolation

| ID | Requirement |
|---|---|
| NFR-S1 | Generated code shall never execute on the host, only in containers per §3.9.3 |
| NFR-S2 | No source code, data, or prompt shall leave the machine (C1) |
| NFR-S3 | Input data shall be treated as sensitive: not logged verbatim beyond the specific failing record required for diagnosis |
| NFR-S4 | Model weights shall be pinned by digest and verified on load |

### 3.10.4 Portability and Determinism

| ID | Requirement |
|---|---|
| NFR-D1 | Given identical inputs, seed, and model digest, two runs shall produce identical Java output |
| NFR-D2 | The system shall run on any x86-64 Linux host meeting §2.4 with no configuration beyond model download |
| NFR-D3 | Model choice shall be a configuration value; swapping models shall require no code change |

### 3.10.5 Maintainability

| ID | Requirement |
|---|---|
| NFR-M1 | Perception, synthesis, verification, repair and memory shall be independently testable modules with no circular dependencies |
| NFR-M2 | Prompts shall reside in a single versioned module, never inline |
| NFR-M3 | The defect taxonomy shall be data-driven and extensible without modifying orchestration logic |

---

# 4. Data Model

## 4.1 FieldSpec
```python
FieldSpec:
    id: str                # "ACCT-REC.AR-BALANCE"
    level: int             # 05
    name: str
    pic: str | None        # "S9(9)V99"
    usage: str             # DISPLAY | COMP-3 | COMP | BINARY
    offset: int            # bytes from start of 01-group
    width: int             # bytes occupied
    digits: int            # total digit positions
    scale: int             # fraction digits from V
    signed: bool
    sign_encoding: str     # NONE | OVERPUNCH_TRAILING | LEADING_SEPARATE | PACKED_NIBBLE
    redefines: str | None
    parent: str | None
    conditions: list[ConditionName]
    java_type: str         # BigDecimal | String | int
```

## 4.2 Paragraph
```python
Paragraph:
    id: str
    name: str              # "2100-CALC-INTEREST"
    line_start: int
    line_end: int
    source: str
    performs: list[str]
    reads: list[str]       # FieldSpec ids
    writes: list[str]
```

## 4.3 MigrationUnit
```python
MigrationUnit:
    id: str
    paragraphs: list[Paragraph]   # >1 only for collapsed cycles
    depends_on: list[str]
    field_context: list[FieldSpec]
    java_method_name: str
    status: PENDING | GENERATING | VERIFYING | REPAIRING | VERIFIED | ESCALATED
    attempts: list[RepairAttempt]
```

## 4.4 DivergenceReport
```python
DivergenceReport:
    unit_id: str
    total_vectors: int
    divergent_count: int
    exit_code_match: bool
    divergences: list[Divergence]

Divergence:
    record_index: int
    byte_offset: int
    field_id: str | None
    oracle_value: str
    candidate_value: str
    numeric_delta: Decimal | None
    input_record: str
```

## 4.5 DefectClassification
```python
DefectClassification:
    defect_class: str
    confidence: float
    evidence: dict
    suggested_strategy: str
    requires_inference: bool
```

## 4.6 FailureCase
```python
FailureCase:
    id: str
    symptom_signature: str    # "numeric|delta<1ulp|scale=2|op=COMPUTE_DIVIDE"
    defect_class: str
    cobol_construct: str      # normalised offending statement
    root_cause: str
    patch: str                # unified diff
    embedding: list[float]    # locally computed
    verified: bool
    hit_count: int
    created_at: datetime
```

## 4.7 TraceEvent
```python
TraceEvent:
    ts: datetime
    run_id: str
    unit_id: str | None
    node: str                 # perceive | plan | generate | verify | classify | repair | escalate
    action: str
    duration_ms: int
    model_calls: int
    tokens_in: int
    tokens_out: int
    memory_hit: bool
    outcome: str
    detail: dict
```

---

# 5. Acceptance Criteria

## 5.1 Functional acceptance

| ID | Criterion | Method |
|---|---|---|
| AC-1 | The oracle compiles and runs the fixture deterministically | 10 consecutive runs, identical output hash |
| AC-2 | ≥ 6 distinct planted defect classes are detected pre-repair | Divergence report against baseline translation |
| AC-3 | Post-repair semantic equivalence ≥ 95% of vectors | Metrics report |
| AC-4 | ≥ 80% of defects resolved without escalation | Metrics report |
| AC-5 | A second program sharing a defect class is repaired with **0** model calls | Trace inspection |
| AC-6 | At least one defect escalates with a complete card per FR-7.2 | Manual inspection |
| AC-7 | `--baseline` produces measurably worse equivalence than the full pipeline | Side-by-side report |

## 5.2 Non-functional acceptance

| ID | Criterion | Method |
|---|---|---|
| AC-8 | Two runs with identical seed produce identical Java | `diff` on output trees |
| AC-9 | Full migration within NFR-P4 budgets | Trace timings |
| AC-10 | Generated code never executes outside a container | Code review + audit of subprocess invocations |

## 5.3 Offline acceptance — mandatory

| ID | Criterion | Method |
|---|---|---|
| **AC-11** | **A complete migration succeeds with all outbound network traffic blocked** | Drop all non-loopback egress (`iptables`/`pfctl`) or physically disconnect; run `weaver migrate`; verify completion |
| AC-12 | Startup aborts if the configured inference host is not loopback | Set a remote host; expect immediate abort |
| AC-13 | No dependency attempts network access at runtime | Traffic capture over a full run; expect loopback only |

**AC-11 shall be executed live during the PRISM final demonstration.**

---

# Appendix A — Local Model Configuration

## A.1 Reference tiers

| Tier | Hardware | Model | Quant | Size | Throughput | Notes |
|---|---|---|---|---|---|---|
| **1** | 8 GB VRAM (RTX 4060 / 3060 Ti) | Qwen2.5-Coder-7B-Instruct | Q4_K_M | ≈ 4.7 GB | 25–40 tok/s | **Reference configuration** |
| **2** | 12–16 GB VRAM | Qwen2.5-Coder-14B-Instruct | Q4_K_M | ≈ 9 GB | 15–25 tok/s | Better on `CONTROL_FLOW` |
| **3** | 16 GB VRAM | DeepSeek-Coder-V2-Lite-Instruct | Q4_K_M | ≈ 10 GB | 20–30 tok/s | MoE; low active params, fast |
| **4** | CPU only, 16 GB RAM | Qwen2.5-Coder-3B-Instruct | Q4_K_M | ≈ 2 GB | 4–8 tok/s | Degraded mode; demo via `--replay` |

Embeddings: `nomic-embed-text` (768-dim) or `all-MiniLM-L6-v2` (384-dim) executed locally. Approximately 0.3 GB.

*Sizes are approximate and should be confirmed against the specific GGUF build used.*

## A.2 Inference parameters

```yaml
model:
  endpoint: http://127.0.0.1:11434    # loopback enforced at startup
  name: qwen2.5-coder:7b
  digest: <pinned sha256>
  temperature: 0.0
  top_p: 1.0
  seed: 42
  num_ctx: 4096
  num_predict: 768
  grammar: schemas/method_body.gbnf
```

## A.3 Why a 7B model is sufficient here

The synthesis task is **not** "write COBOL" (where [R3] shows even frontier models perform poorly). It is: *given one 15-line COBOL paragraph, an explicit typed field table, and a Java method signature, emit a method body.* Field decoding, scaling, I/O and edit masks are already supplied deterministically (FR-3.1). What remains is short, well-scaffolded Java generation — squarely within a 7B coder model's competence.

Where the model is wrong, the differential harness catches it and the repair loop corrects it. **Model weakness is a design assumption, not a risk** — which is precisely why the local constraint strengthens rather than weakens the architecture.

---

# Appendix B — Demonstration Fixture

`INTCALC.cbl` — daily interest accrual, ~250 lines, one copybook, sequential flat file I/O.

| Trap | Construct | Failure mode if mistranslated |
|---|---|---|
| T1 | `COMPUTE` without `ROUNDED` | Sub-paisa error per record, compounding in totals |
| T2 | `PIC S9(9)V99` implied decimal | 100× magnitude error |
| T3 | `REDEFINES` on flag bytes | Dormant accounts incorrectly accrue interest |
| T4 | 88-level tiered rate condition | Wrong rate branch selected |
| T5 | `PIC -9(9).99` edit mask | Fixed-width alignment corruption |
| T6 | `PERFORM VARYING ... AFTER` | Final record dropped |

T1 is guaranteed to diverge by COBOL language semantics — `COMPUTE` truncates unless `ROUNDED` is specified, whereas generated Java will round or use binary floating point. The demonstration defect is therefore **structurally certain**, not dependent on the model happening to make a mistake.

`FEECALC.cbl` (~80 lines) shares defect class T1 and exists solely to demonstrate FR-6.3: zero-inference repair via memory retrieval.

---

# Appendix C — Requirements Traceability to PRISM Theme 1 Criteria

| Criterion | Weight | Requirements |
|---|---|---|
| Agentic Intelligence | 25% | FR-2.1–2.3, FR-5.1–5.5, FR-6.1–6.5, FR-7.1–7.3 |
| Innovation & Originality | 20% | FR-4.1–4.5 (oracle-based verification), FR-6.3 (zero-inference repair), C1 (air-gapped operation) |
| Technical Implementation | 20% | FR-1.1–1.6, FR-3.1–3.5, §3.9.3, NFR-S1–S4, NFR-D1–D3 |
| Real-World Impact & Feasibility | 15% | C1, §2.1.1, App. A (commodity hardware), FR-7.2 |
| User Experience & Demonstration | 10% | FR-2.3, FR-8.1–8.4, §3.9.4 |
| Presentation & Communication | 10% | FR-8.2–8.3 (measured, not asserted, results); AC-11 live |

---

**End of document.**
