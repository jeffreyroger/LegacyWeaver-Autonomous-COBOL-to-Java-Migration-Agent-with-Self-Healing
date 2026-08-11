# LegacyWeaver — Agent Layer Implementation Runbook

**Document type:** Execution plan, Phase 2
**Version:** 1.0
**Precondition:** MVP complete — oracle verified, differential runner reporting 113/200, zero false positives
**Window:** Aug 9 → Aug 11 (build) · Aug 12 (finale)
**Scope:** The model-invoking components. This is what makes "AI agent" true rather than aspirational.

---

## What this phase adds

The MVP can *detect* defects. It cannot *fix* them, and it contains no model. This phase builds four things:

| Component | What it does | Makes which claim true |
|---|---|---|
| **Synthesis** | Generates Java method bodies from COBOL paragraphs | "It migrates" |
| **Repair loop** | Diagnoses a divergence, patches, re-verifies, bounded | "It self-heals" |
| **Failure memory** | Reuses verified patches with zero inference | "It gets cheaper with use" |
| **Orchestrator** | Decides what to do next, autonomously, until done or stuck | "It is an agent" |

Without the orchestrator the other three are just functions. The state machine is what converts a pipeline into an agent, and it is the component judges will actually probe.

## The critical design decision, restated

**The model writes roughly 20% of the emitted Java.** Everything determined by the copybook — field decoders, byte offsets, decimal scaling, edit masks, the record loop, file I/O — is generated deterministically. The model receives one paragraph at a time and returns one method body.

This is not a compromise forced by local inference. It is what makes local inference viable, and it is the reason correctness belongs to the harness rather than to a prompt. Do not let scope creep move work back into the model.

---

## Phase J — Local Inference (Aug 9 morning, 1.5 h)

### Step J1 — Install the runtime and pull the model **[MUST]**

**Objective.** A local model responding on loopback, with pinned behaviour.

**Owner:** Dev B · **Duration:** 30 min (plus download time — start this first, it runs in background)

**Procedure.**
1. Install Ollama, or build llama.cpp with its server binary. Ollama is faster to stand up and exposes an OpenAI-shaped API; prefer it unless someone on the team already knows llama.cpp well.
2. Pull `qwen2.5-coder:7b`. Approximately 4.7 GB at Q4_K_M. **Start the download before anything else in this phase** — everything else can proceed while it runs.
3. Also pull the 3B variant as the CPU-only fallback, and `nomic-embed-text` for Phase O.
4. Confirm the service binds to loopback only. If it is listening on `0.0.0.0`, restrict it — the offline claim must be structurally true, not merely unexercised.
5. Record the model digest. It goes in the configuration and in the deck.

**Acceptance test.** A trivial completion request to the loopback endpoint returns text. Record tokens per second — you need this number for Step J3.

**Common failures.**
- *Model loads into system RAM rather than VRAM* — throughput drops roughly 5×. Confirm GPU offload is active; on 8 GB VRAM the 7B Q4 model should fit entirely.
- *Service bound to all interfaces* — fix now, not on Aug 12 in front of judges.

---

### Step J2 — Pin determinism **[MUST]**

**Objective.** Two runs with the same inputs must produce the same Java. Without this you cannot debug, cannot demo reliably, and cannot claim reproducibility.

**Owner:** Dev B · **Duration:** 20 min

**Procedure.**
1. Set temperature to 0, top-p to 1, and a fixed seed in the request parameters.
2. Set the context window to 4096 and the prediction cap to around 768 tokens. A paragraph body that needs more than 768 tokens indicates your granularity is wrong, not that the cap is too low.
3. Send the same request five times and compare responses.

**Acceptance test.** Five identical requests return five identical responses.

**Common failures.**
- *Responses vary despite temperature 0* — some runtimes ignore seed unless it is explicitly set per-request rather than per-session. Set it on every call.

---

### Step J3 — Measure and budget latency **[MUST]**

**Objective.** Know your inference budget before designing around it. This number determines whether the Aug 12 demo runs live or from replay.

**Owner:** Dev B · **Duration:** 20 min

**Procedure.**
1. Time a representative synthesis request — roughly 900 tokens in, 400 out.
2. Multiply by your unit count (5 paragraphs) and add expected repair attempts (budget 2 per unit average). This is your worst-case wall-clock for a full run.
3. Compare against the demo budget: the live agent run has roughly **2 minutes** of stage time.

**Acceptance test.** Full-run estimate is recorded and a decision is made explicitly:

| Estimated full run | Demo strategy |
|---|---|
| Under 90 s | Run live. Best outcome |
| 90 s – 4 min | Run live with a pre-warmed cache for early units; narrate over the slow parts |
| Over 4 min | **Demo from replay cache.** Decide this now, not on Aug 12 |

**Do not treat replay as failure.** A deterministic replay of a real run is a legitimate demo. An unreliable live run that stalls at minute three is not.

---

### Step J4 — Build the caching layer **[MUST]**

**Objective.** Every model interaction is cached by prompt hash. This is simultaneously a development accelerator, the replay mechanism, and your insurance against a stalled demo.

**Owner:** Dev B · **Duration:** 20 min

**Procedure.**
1. Hash the full request payload — model name, seed, all parameters, and the complete prompt. Any change to any of these must miss the cache.
2. Store responses keyed by that hash on disk.
3. Add a replay mode that serves only from cache and raises on a miss rather than falling through to inference. A silent fallthrough during a demo is exactly the failure you are insuring against.

**Acceptance test.** A second identical run completes with zero inference calls. Replay mode raises loudly on a deliberate cache miss.

---

## Phase K — Deterministic Scaffold (Aug 9 midday, 2.5 h)

This phase contains no AI and is the most important in the document. **If the scaffold is wrong, the model will be blamed for scaffold defects** — and you will spend Aug 11 tuning prompts to fix a byte-offset bug.

### Step K1 — Define the generated class shape **[MUST]**

**Objective.** Decide the structure the model writes into, before writing any generator.

**Owner:** Dev A · **Duration:** 30 min

**Procedure.** Specify on paper:
1. **A record type per 01-level group**, with one component per field. Every numeric field is exact-decimal at the scale implied by its PIC clause. No floating point anywhere in generated output.
2. **A decoder** taking a fixed-width line and producing that record, slicing by the byte offsets from your existing field table. This must handle the trailing-separate sign and the `REDEFINES` overlay — the overlay is a second accessor over the same byte range, not a separate field.
3. **An encoder** producing the fixed-width output line, replicating each declared edit mask including width, alignment, and sign placement.
4. **A working-storage holder** for the program's mutable state, mirroring the COBOL working-storage section.
5. **One method stub per paragraph**, with a uniform signature taking the current record and the working-storage holder. Uniform signatures matter: they let the orchestrator swap one body without touching anything else.
6. **A main loop** that opens the file, iterates records, calls the paragraph methods in the program's control-flow order, and writes output.

**Acceptance test.** The specification is written and reviewed by Dev B. Every field in the copybook maps to exactly one record component, and every paragraph maps to exactly one stub.

---

### Step K2 — Generate the scaffold **[MUST]**

**Objective.** Emit everything except paragraph bodies, from the field table alone.

**Owner:** Dev A · **Duration:** 90 min · **Prerequisites:** K1

**Procedure.**
1. Generate from the parsed field table — never from the COBOL source text. The field table is already validated; re-parsing introduces a second place to be wrong.
2. Emit paragraph methods with bodies that throw or return immediately, clearly marked as unimplemented.
3. Emit deterministically: identical field table produces byte-identical scaffold. Sort anything iterated from a map.
4. Compile the scaffold with empty bodies to prove it is structurally valid before any model involvement.

**Acceptance test.** Scaffold compiles. Two generations produce identical output. Running it produces an empty or stub report rather than crashing.

**Common failures.**
- *Decoder off by one after the first numeric field* — the implied decimal marker occupies zero bytes. This is the single most common COBOL data error and it cascades through every subsequent field.
- *`REDEFINES` accessor extends the record* — it must read the same bytes as its target, not appended bytes.

---

### Step K3 — Build the reference implementation **[MUST]**

**Objective.** A hand-written, known-correct set of paragraph bodies. This is the most valuable de-risking step in the entire phase.

**Owner:** Dev A · **Duration:** 45 min · **Prerequisites:** K2

**Reasoning.** When the model's output diverges, you need to know whether the fault lies in the model, the scaffold, the decoder, or the encoder. With a reference implementation that reaches zero divergences, you have proof the scaffold is sound — so every subsequent divergence is attributable to the model, which is exactly the signal the repair loop needs.

**Procedure.**
1. Hand-write the paragraph bodies correctly: exact decimal arithmetic, truncation toward zero, the `REDEFINES` overlay honoured, the premium tier's double truncation preserved.
2. Assemble with the scaffold and compile.
3. Run the differential comparison.

**Acceptance test.** **Zero divergences against the oracle.** This is a hard gate. Do not proceed to Phase M until it passes.

**Common failures.**
- *A handful of divergences remain* — almost always the premium path, where the rate is truncated to five decimals *before* being used. There are two truncations, not one.
- *All 201 lines diverge* — an encoder problem, typically padding or alignment, not arithmetic.

---

## Phase L — Perception for Synthesis (Aug 9 afternoon, 1.5 h)

### Step L1 — Segment paragraphs **[MUST]**

**Objective.** Split the procedure division so the model sees one paragraph at a time.

**Owner:** Dev C · **Duration:** 45 min

**Procedure.**
1. Identify paragraph headers: non-comment lines beginning in Area A (columns 8–11), consisting of a label terminated by a period.
2. Each paragraph runs from its header to the line before the next header.
3. Record identifier, source line range, and verbatim text.
4. Verify the count against a manual read of the source.

**Acceptance test.** All paragraphs found, boundaries correct, no source lines lost or duplicated between paragraphs.

---

### Step L2 — Build the data context **[MUST]**

**Objective.** Determine which fields each paragraph touches. This is what keeps prompts small and focused.

**Owner:** Dev C · **Duration:** 45 min · **Prerequisites:** L1

**Procedure.**
1. For each paragraph, match identifiers in its text against the field table.
2. Classify as read or written using the statement verb: assignment and arithmetic targets are written, everything else is read. Precision is not required — over-inclusion costs prompt tokens, not correctness.
3. Attach any condition names whose parent field appears in the paragraph. The tiered-rate logic is unreachable without them.
4. If a paragraph's context comes out empty, fall back to the full field table rather than sending nothing.

**Acceptance test.** The interest-calculation paragraph's context includes balance, rate, type, the dormant flag, and the premium condition name. If the dormant flag is missing, the model cannot possibly get that logic right and you will misattribute the failure.

---

## Phase M — Synthesis (Aug 9 evening → Aug 10 morning, 3 h)

### Step M1 — Design the prompt **[MUST]**

**Objective.** Constrain the model so tightly that it has little room to be wrong.

**Owner:** Dev B · **Duration:** 60 min · **Prerequisites:** K3, L2

**Structure the prompt in this order.** Ordering matters — constraints stated after the task get weaker adherence than constraints stated before it.

1. **Role.** One sentence: translating a single COBOL paragraph into the body of one Java method.
2. **Semantic rules, stated as absolutes.** These carry most of the correctness burden:
   - Arithmetic truncates toward zero unless the source says `ROUNDED`. This is COBOL's default and the opposite of Java's convention.
   - All numeric values are exact decimal at their declared scale. Binary floating point is forbidden.
   - A `REDEFINES` field reads the same bytes as its target and is accessed through the provided accessor.
   - Condition names are evaluated against their parent field, not compared as strings.
3. **Field table** for this paragraph's context: name, PIC clause, scale, sign encoding, and the Java accessor to use for each.
4. **Condition names** in scope with their value sets.
5. **The method signature** the body must fit.
6. **Prohibitions**, explicit: no new fields, no helper methods, no modification of the scaffold, no floating-point types, no rounding calls.
7. **The paragraph source**, verbatim.
8. **Output contract**: a JSON object containing the method body and a list of assumptions made.

**Acceptance test.** Dev A reviews and confirms every semantic rule that caused a planted trap is explicitly stated. If a trap's rule is absent, the model will fall into it and you will have learned nothing about whether the loop works.

---

### Step M2 — Constrain and validate output **[MUST]**

**Objective.** Never let malformed model output reach the compiler.

**Owner:** Dev B · **Duration:** 45 min

**Procedure.**
1. Constrain generation to a JSON schema using the runtime's grammar support. This eliminates the single most common local-model failure — prose wrapped around the answer, or fenced code blocks.
2. Validate on receipt: well-formed JSON, schema conformant, required keys present.
3. Apply a static rejection pass over the returned body: reject any occurrence of floating-point types, rounding calls, or references to identifiers not in the supplied context.
4. On validation failure, regenerate up to twice, then classify as a synthesis failure and escalate. **Do not attempt to repair malformed output** — regenerating is cheaper and more reliable than patching syntax.

**Acceptance test.** Malformed responses are rejected before compilation. A deliberately floating-point body is caught by the static pass rather than by the differential runner.

---

### Step M3 — Assemble and compile **[MUST]**

**Objective.** Combine scaffold and synthesised bodies into a compiling program.

**Owner:** Dev B · **Duration:** 45 min · **Prerequisites:** K2, M2

**Procedure.**
1. Substitute each synthesised body into its stub.
2. Compile.
3. On compilation failure, capture the compiler's diagnostics with line numbers and map them back to the owning paragraph. **Do not send raw compiler output into the repair loop** — map it to a unit first, or the loop cannot know what to fix.

**Acceptance test.** A full synthesis pass produces a compiling program, or produces compiler diagnostics correctly attributed to specific units.

---

### Step M4 — First honest measurement **[MUST]**

**Objective.** Find out how good the model actually is, unassisted. This number is a slide.

**Owner:** Dev B · **Duration:** 30 min · **Prerequisites:** M3

**Procedure.**
1. Synthesise all paragraphs, assemble, compile, and run the differential comparison. **No repair.**
2. Record: units synthesised, units compiling, divergences, and which planted traps the model fell into.

**Acceptance test.** The run completes and produces a number.

**Interpretation — and this matters.** A high divergence count here is **good for your argument**, not bad. It is the empirical case for why the harness must exist. If a 7B model produced perfect COBOL translation unassisted, your project would have no reason to exist. Expect it to handle the straightforward arithmetic and fall into truncation and the `REDEFINES` overlay.

Record this as your *unassisted synthesis* baseline. The delta between it and the post-repair number is the contribution of the agent loop, and it is the most persuasive measurement in the project.

---

## Phase N — The Repair Loop (Aug 10, 4 h)

This is the agent. Everything before it is infrastructure.

### Step N1 — Attribute divergences to units **[MUST]**

**Objective.** Solve a subtle problem that will otherwise waste hours.

**Owner:** Dev A · **Duration:** 45 min

**The problem.** Only the whole program produces output. When the differential runner reports a divergence, which paragraph caused it? The runner compares final output, not per-method behaviour.

**The solution — migrate in dependency order, one unit at a time.**
1. Start from the reference implementation, where all bodies are known correct and divergence is zero.
2. Replace exactly one body with the synthesised version.
3. Verify. Any divergence that appears is attributable to that unit, because nothing else changed.
4. On success, commit that body and move to the next unit in topological order.

This gives clean attribution with no instrumentation, and it makes the unit rail in the UI meaningful — units genuinely go green one at a time, in dependency order.

**Acceptance test.** Deliberately corrupting one synthesised body produces divergences attributed to exactly that unit.

**Note.** State plainly that the reference implementation is scaffolding for attribution, not part of the product. Concealing it would be dishonest; explaining it is a strength, because it shows you thought about experimental control.

---

### Step N2 — Deterministic repair strategies **[MUST]**

**Objective.** Fix three of five defect classes with no inference at all.

**Owner:** Dev C · **Duration:** 60 min

**Procedure.** Implement rule-based patchers for the classes fully determined by the field specification:

| Class | Patch | Why no model is needed |
|---|---|---|
| `PADDING` | Re-emit through the declared edit mask — width, alignment, sign placement | The mask is in the field table |
| `SCALE` | Recompute the scale from the implied-decimal position | The PIC clause states it |
| `SIGN` | Correct the sign decode per the declared encoding | The encoding is declared |

Each patcher operates on the method body and returns a modified body plus a description of what it changed.

**Acceptance test.** Each patcher, given a body with its target defect, produces a body that verifies clean.

**Why this matters for your pitch.** "Three of five repair strategies use no model at all" is a strong claim. It demonstrates the architecture puts inference where inference is needed and computation where computation suffices — which is the difference between an engineered system and a prompt loop.

---

### Step N3 — Model-assisted repair **[MUST]**

**Objective.** Handle the classes that genuinely require interpretation.

**Owner:** Dev B · **Duration:** 75 min · **Prerequisites:** M1, N1

**Procedure.** For `TRUNCATION`, `CONTROL_FLOW`, and `COMPILE_ERROR`, build a repair prompt containing:
1. The current method body.
2. The originating COBOL paragraph.
3. **The failing input record**, verbatim.
4. Oracle value, candidate value, and delta.
5. The defect classification and its confidence.
6. A strategy hint specific to the class.
7. **Every previous attempt for this unit and why each failed.** Without this the model repeats itself — reliably, since temperature is zero.
8. The same output contract as synthesis.

**Acceptance test.** A truncation defect is repaired within three attempts.

**Common failures.**
- *The model repeats a previous patch* — attempt history is missing or not being included. This is the single most common repair-loop bug.
- *Repair fixes one record and breaks four* — Step N4 catches this.

---

### Step N4 — Bounding and the regression guard **[MUST]**

**Objective.** Make the loop terminate, and never accept a patch that makes things worse.

**Owner:** Dev A · **Duration:** 45 min

**Procedure.**
1. Cap attempts at three per unit.
2. Hash every patch. A repeated hash terminates immediately and escalates — do not spend the remaining budget on a model that has stopped generating new ideas.
3. After every patch, re-verify against the **full** input set, not only the failing record.
4. If total divergence count increases, revert the patch and record the attempt as failed. A patch that fixes the reported record while breaking others is a regression, and accepting it would make the loop oscillate.
5. Enforce a wall-clock cap per unit independent of the attempt cap.

**Acceptance test.** A deliberately unfixable defect terminates in bounded time and escalates. A regressing patch is reverted.

**Why this is worth stage time.** A bounded loop that shows its bound — "attempt 2 of 3" in the UI — reads as engineered. An unbounded loop reads as hopeful. Judges notice the difference.

---

## Phase O — Failure Memory (Aug 10 evening, 2 h)

### Step O1 — Design the symptom signature **[MUST]**

**Objective.** A compact key that matches the same defect class across different programs. This determines whether memory works at all.

**Owner:** Dev B · **Duration:** 30 min

**Procedure.** Compose the signature from **structural properties only** — never from specific values, or nothing will ever match:
- Value kind (numeric or alphanumeric)
- Delta magnitude bucket (below one unit in the last place, a power of ten, sign inversion)
- Field scale
- The normalised COBOL operation — the offending statement with identifiers replaced by placeholders and whitespace collapsed

**Acceptance test.** The truncation defect in the interest program and the truncation defect in the fee program produce signatures with cosine similarity above 0.85, while a padding defect scores well below it.

**Common failure.** *Nothing ever matches* — the signature includes specific values or field names. Normalise harder.

---

### Step O2 — Store and retrieve **[MUST]**

**Objective.** Persistent, local, retrieval-first repair.

**Owner:** Dev B · **Duration:** 60 min · **Prerequisites:** O1

**Procedure.**
1. Embed signatures with the local embedding model. No embedding API.
2. Store in a file-backed vector index with metadata alongside: defect class, normalised construct, root cause, patch, verification status, hit count.
3. **Query before any inference.** On similarity above 0.85, apply the stored patch and verify — zero model calls.
4. On verification failure after a memory hit, decrement that case's confidence and fall through to normal repair.
5. Write back every verified repair.

**Acceptance test.** A repair verified in run one is retrieved and applied in run two with zero inference calls.

---

### Step O3 — Seed honestly **[MUST]**

**Objective.** Populate memory with real cases.

**Owner:** Dev B · **Duration:** 30 min

**Procedure.** Seed with three cases discovered during development — actual failures your loop actually diagnosed and fixed. Record their provenance.

**Do not fabricate entries.** A judge who asks where a case came from deserves a true answer, and "we hand-wrote it to make the demo work" is a bad one to have to give.

---

## Phase P — Orchestrator (Aug 11 morning, 2.5 h)

### Step P1 — Define the state machine **[MUST]**

**Objective.** This is the component that makes the system an agent rather than a pipeline.

**Owner:** Dev A · **Duration:** 45 min

**Procedure.** Define nodes and transitions explicitly:

```
perceive → plan → [next unit] → synthesise → compile
                        ▲                        │
                        │                   ┌────┴────┐
                        │              fail │         │ ok
                        │                   ▼         ▼
                        │              classify ← verify
                        │                   │         │
                        │                   ▼         │ pass
                        │            memory lookup    │
                        │                   │         ▼
                        │              hit / miss   commit
                        │                   │         │
                        │                   ▼         │
                        │                repair       │
                        │                   │         │
                        │              [attempts<3]   │
                        │                   │         │
                        │                   └─────────┤
                        │                             │
                        └─────────────────────────────┘
                                       │
                           [attempts=3] ▼
                                   escalate
```

Persist state per unit so a run is resumable. Emit a structured event on every transition — this stream is what the UI renders and what your metrics are computed from.

**Acceptance test.** The graph is drawn, reviewed, and matches the architecture diagram in the deck. Divergence between the two is a presentation bug.

---

### Step P2 — Implement and instrument **[MUST]**

**Owner:** Dev A · **Duration:** 90 min · **Prerequisites:** P1, N4, O2

**Procedure.**
1. Implement the graph.
2. Emit a trace event per transition: timestamp, unit, node, action, duration, model calls, tokens, memory hit, outcome.
3. Continue with independent units after an escalation. **Never halt the whole run on one failure** — partial progress is the correct behaviour and it demonstrates judgement.
4. Persist trace to disk as newline-delimited JSON.

**Acceptance test.** A full run completes autonomously from COBOL source to verified Java, with a complete trace, no human intervention, and at least one escalation handled without halting.

---

## Phase Q — Escalation (Aug 11 midday, 1 h)

### Step Q1 — Build the diagnostic record **[MUST]**

**Objective.** When the agent gives up, it must give up *well*. This is a credibility asset, not a failure screen.

**Owner:** Dev C · **Duration:** 45 min

**Contents.** Unit identifier · failing input record · oracle and candidate values with delta · defect class and confidence · **every attempt, the patch applied, and why it failed** · assumptions the model recorded during synthesis · suspected source lines · the decision requested.

**Acceptance test.** The record contains all nine elements and is readable without reference to the codebase.

**Why this earns more than a clean run.** It demonstrates the agent tried distinct approaches, evaluated each against evidence, knew when to stop, and localised the problem before asking for help. Every judge has seen demos that only work. Few have seen one that fails competently.

---

## Phase R — Measurement (Aug 11 afternoon, 1.5 h)

### Step R1 — Compute the metrics **[MUST]**

**Owner:** Dev D · **Duration:** 45 min

From the trace, compute:

| Metric | Why it is on a slide |
|---|---|
| Equivalence rate, unassisted synthesis | Establishes the model alone is insufficient |
| Equivalence rate, post-repair | Establishes the loop works |
| Mean repair attempts per unit | Shows convergence, not thrashing |
| Autonomous resolution rate | The headline agentic number |
| Model calls per defect, run 1 vs run 2 | The memory argument |
| Wall clock and inference time | Feasibility |

### Step R2 — The three-way comparison **[MUST]**

**Owner:** Dev D · **Duration:** 45 min

Run all three configurations against the same fixture and the same harness:

| Configuration | What it isolates |
|---|---|
| Naive single-shot translation | The MVP baseline — 113 divergences |
| Unassisted synthesis, no repair | What the local model contributes |
| Full agent loop | What the harness contributes |

**This table is your strongest slide.** It separates the model's contribution from the architecture's, which is exactly the question a sceptical judge is holding.

---

## Phase S — Memory Demonstration (Aug 11 evening, 1.5 h)

### Step S1 — Build the second program **[MUST]**

**Owner:** Dev A · **Duration:** 45 min

**Procedure.** Write `FEECALC` — roughly 80 lines, flat fee tiers, sharing the truncation defect class with the interest program but with different arithmetic and different field names. Different enough that a superficial match fails; structurally similar enough that the signature matches.

**Acceptance test.** Compiles, runs, produces a golden output, and its truncation defect is genuinely the same class.

### Step S2 — Verify the zero-inference path **[MUST]**

**Owner:** Dev B · **Duration:** 45 min

**Procedure.** Run the interest program first so memory populates. Then run the fee program and confirm the truncation defect resolves from memory with zero model calls.

**Acceptance test.** Trace shows a memory hit, zero inference calls, and a resolution time under a second.

**This is the most persuasive twenty seconds of the demo.** The first repair takes several seconds and several model calls. The second is instant and free. The timestamps make the argument; no narration is required.

---

## Phase U — Fixture Breadth (Aug 11, post-demo-prep; user-authorized 2026-08-11)

Not part of the original demo critical path. Added on explicit user direction
after S1/S2 to show the harness generalizes across genuinely different
control-flow shapes, not just a second flat-fee lookup that happens to share
FEECALC's truncation defect class. Extended to four programs (U1-U4) on
further explicit user direction (2026-08-12) -- still a closed, disclosed
set, not an open-ended library, per the user's own "not to overload it"
constraint from U1/U2's authorization.

### Step U1 — Build a nested-conditional program **[MUST]**

**Procedure.** Write `TAXCALC` — a single synthesis paragraph whose logic is
a nested IF/ELSE bracket ladder (progressive tax-style thresholds), as
opposed to FEECALC's flat EVALUATE lookup or interest.cob's single-level
88-level branch. Same record-oriented shape (one paragraph per input
record, no in-paragraph loop) so it reuses the existing scaffold generator
and orchestrator unchanged.

**Acceptance test.** Compiles under GnuCOBOL 3.x, runs, produces a
golden output; `weaver verify` against a deliberately-broken candidate
correctly attributes and classifies the divergence.

### Step U2 — Build an in-paragraph-loop program **[MUST]**

**Procedure.** Write `TIERACCUM` — a single synthesis paragraph whose logic
contains a `PERFORM VARYING` loop internal to the paragraph (accumulating a
tiered value across sub-units within one record), as opposed to every prior
program's loop living only in the scaffold's per-record main loop. Tests
whether the synthesis prompt's per-paragraph framing (K1: "one paragraph's
logic, not the whole program") still holds when that one paragraph's logic
is itself iterative.

**Acceptance test.** Same as U1: compiles, runs, produces a golden output,
`weaver verify` correctly attributes a planted defect.

### Step U3 — Build a pure-arithmetic program **[MUST]**

**Procedure.** Write `COMPOUND` — a single synthesis paragraph with no
`IF`, `EVALUATE`, or `PERFORM` at all: a straight-line chain of four
sequential `COMPUTE` statements, each depending on the previous step's
result. Different from every prior fixture by having *no branching or
looping whatsoever* -- the divergence risk is purely in chained truncation
across steps, not in which path is taken.

**Acceptance test.** Same as U1/U2: compiles under GnuCOBOL 3.x, runs,
produces a golden output; `weaver verify` against a deliberately-broken
candidate correctly attributes and classifies the divergence.

### Step U4 — Build a compound-condition lookup program **[MUST]**

**Procedure.** Write `SHIPCOST` — a single synthesis paragraph using
`EVALUATE TRUE` with compound `AND` conditions spanning two different
input fields (weight and zone), as opposed to FEECALC's flat single-field
`EVALUATE` or TAXCALC's nested single-field `IF/ELSE` ladder. Tests
whether the synthesis prompt's field table still holds when a single
`WHEN` clause's condition references more than one accessor at once.

**Acceptance test.** Same as U1/U2/U3.

**Explicitly out of scope for Phase U:** cross-program failure-memory
transfer between these four and FEECALC/interest (that guarantee is S2's,
proven once, not re-proven per fixture); autonomous `weaver migrate`
success is not required for any of them (feecalc.cob itself already
demonstrates that success is model-capability-dependent, not an
infrastructure guarantee -- see 2026-08-11 CLAUDE.md session notes). These
four programs exist to prove `weaver verify`/attribution generalize to new
control-flow shapes without scaffold.py/prompt.py changes beyond what Step
S1's ScaffoldSpec generalization already provides.

---

## Phase T — Demo Preparation (Aug 11 night, 2 h)

### Step T1 — Freeze **[MUST]**
**20:00 Aug 11.** No new features. Anything unfinished is roadmap.

### Step T2 — Cache the demo run **[MUST]**
Execute the full demo path successfully and cache every model interaction. Verify replay mode reproduces it exactly with zero inference.

### Step T3 — Record the backup video **[MUST]**
Full five-minute demo, screen and audio. If the venue network or a GPU driver fails on Aug 12, this is the project.

### Step T4 — Rehearse **[MUST]**
Four timed run-throughs. Dev D narrates, Dev A drives. Never the same person. Time to 4:30, not 5:00.

---

## Time Budget

| Phase | Hours | Cumulative |
|---|---|---|
| J — Inference setup | 1.5 | 1.5 |
| K — Scaffold | 2.5 | 4.0 |
| L — Perception | 1.5 | 5.5 |
| M — Synthesis | 3.0 | 8.5 |
| N — Repair loop | 4.0 | 12.5 |
| O — Memory | 2.0 | 14.5 |
| P — Orchestrator | 2.5 | 17.0 |
| Q — Escalation | 1.0 | 18.0 |
| R — Measurement | 1.5 | 19.5 |
| S — Memory demo | 1.5 | 21.0 |
| T — Demo prep | 2.0 | 23.0 |

Roughly 23 person-hours across three days and four people. Achievable with parallelism — provided Phase K is not rushed.

## Hard Gates

Stop and fix rather than proceeding:

| Gate | Condition | If it fails |
|---|---|---|
| **K3** | Reference implementation reaches zero divergences | The scaffold is wrong. Every model failure after this point is misattributed |
| **N1** | Divergences attribute to the correct unit | The repair loop cannot know what to fix |
| **N4** | Loop terminates and reverts regressions | The loop will oscillate on stage |
| **T2** | Replay reproduces the demo exactly | You have no fallback |

## Cut Order

From the top when behind:

1. `CONTROL_FLOW` model-assisted repair — always escalate that class instead
2. `FEECALC` and the memory demo — describe it, show the schema
3. Assumption capture in synthesis
4. Wall-clock caps — keep the attempt cap
5. Resumability

**Never cut:** the reference implementation (K3), unit attribution (N1), the regression guard (N4), the three-way comparison (R2), the demo cache (T2).

---

## What to say on stage about the model

Be direct about the division of labour. It is your strongest technical position and it pre-empts the sharpest question:

> A 7B model running on this laptop wrote about a fifth of this Java. It got the truncation semantics wrong, which we expected — that is what the benchmark predicts. The harness caught it, classified it, and fixed it in two attempts. The second time it saw that defect class, it fixed it in forty milliseconds with no model call at all.
>
> The intelligence here is not in the model. It is in the loop around it.
