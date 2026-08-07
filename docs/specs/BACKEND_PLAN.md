# LegacyWeaver — Backend Implementation Plan

**Document type:** Implementation plan with SRS conformance validation
**Version:** 1.0
**Validates against:** LegacyWeaver SRS v1.0 (full) and MVP SRS v1.0
**Precondition:** MVP complete · agent layer complete
**Window:** Aug 11, ~6 hours
**Component:** Local run service — the transport and lifecycle layer between the agent and the frontend

---

# Part I — Scope and the Central Constraint

## 1.1 What the backend is

A **local HTTP service** that starts agent runs, exposes their state, and streams their trace events to a browser. It binds to loopback and serves exactly one user: the person sitting at the machine.

## 1.2 What the backend is not

This is the most important section in the document.

> **The backend contains no domain logic.** It starts runs, tracks their lifecycle, and forwards events. It does not compare output, does not classify defects, does not decide whether a candidate is verified, and does not transform trace events beyond serialisation.

SRS **DC-4** states that correctness is determined solely by byte comparison, with no heuristic or model participating. **DC-5** requires every externally presented result to be reproducible from a clean checkout. If the API layer computes, filters, rounds, or derives anything, both are violated — the browser would be showing a number the CLI cannot reproduce, and there would be two places where correctness is decided.

**Test to apply throughout:** for any value the API returns, the identical value must be obtainable from `weaver verify` on the command line. If it is not, the backend is doing something it should not.

## 1.3 Why a service is needed at all

The frontend design specifies streaming rows at printer cadence, a live trace rail, and unit status transitions. A run takes 20–200 seconds. A browser cannot invoke a Python function, and a blocking request that returns after three minutes gives the UI nothing to render in the meantime.

The service exists to make an inherently long-running, event-producing process observable from a browser. Nothing more.

---

# Part II — SRS Conformance Audit

Before building, validate what exists. Each requirement is assessed as **PASS** (satisfied), **GAP** (must be built in this phase), or **RISK** (satisfied but the backend could break it).

## 2.1 Requirements the backend must satisfy

| SRS ID | Requirement | Status | Action |
|---|---|---|---|
| FR-8.1 | Every state transition appended as a structured trace event | **GAP** | Trace is written to disk but not exposed. §4.3 |
| FR-8.2 | Metrics computed and reported on completion | **RISK** | Must be computed by the agent, **not** the API. §4.4 |
| FR-8.4 | All model interactions cached; replay serves only from cache | **PASS** | Backend must expose replay as a run parameter, not reimplement it |
| §3.9.1 | CLI command surface | **PASS** | Backend must not diverge from it. §3.4 |
| §3.9.2 | Inference endpoint validated as loopback; abort otherwise | **RISK** | Validation must run on service startup too, not only CLI. §5.2 |
| §3.9.3 | Containers with no network, read-only, memory and wall-clock bounds | **PASS** | Backend must not relax these when invoking runs |
| §3.9.4 | Terminal UI mandatory, web UI desirable | **PASS** | Backend is additive; CLI must keep working standalone |
| NFR-R1 | One unit's failure must not prevent independent units | **PASS** | Backend must surface partial progress, not just terminal state |
| NFR-R2 | Run state checkpointed per unit, resumable after interruption | **GAP** | §4.5 |
| NFR-R3 | Inference unavailability degrades, does not crash | **RISK** | Backend must return a degraded status, not a 500 |
| NFR-S1 | Generated code never executes on the host, only in containers | **PASS** | Backend must not add a host-execution path for convenience |
| NFR-S2 | No source, data, or prompt leaves the machine | **RISK** | An HTTP server is the most likely way to violate this. §5.1 |
| NFR-S3 | Input data not logged verbatim beyond the failing record | **RISK** | Trace events cross a network boundary now. §5.3 |
| NFR-D1 | Identical inputs, seed, model digest → identical output | **RISK** | Run parameters must be captured and echoed. §4.2 |
| NFR-M1 | Modules independently testable, no circular dependencies | **RISK** | The API must depend on the agent; the agent must never import the API. §3.3 |
| DC-1 | No network egress at runtime | **RISK** | §5.1 |
| DC-4 | Correctness by byte comparison only | **RISK** | §1.2 |
| DC-5 | Results reproducible from clean checkout | **RISK** | §1.2 |

## 2.2 Summary

**Two genuine gaps:** trace event streaming (FR-8.1) and run resumability (NFR-R2).

**Ten risks**, and every one is a risk *introduced by adding a server*. That is the honest characterisation of this phase: the backend adds little capability and considerable opportunity to violate constraints the system currently satisfies for free. Build it defensively.

## 2.3 The one requirement that changes character

**NFR-S2** — nothing leaves the machine. Today this is true because there is no network code. After this phase there is a listening socket, and it becomes true only by construction. §5.1 specifies how, and §7.2 specifies how it is proven.

---

# Part III — Architecture

## 3.1 Process model

```
┌──────────────────── localhost ────────────────────┐
│                                                   │
│  Browser ──HTTP/SSE──▶ Run Service (127.0.0.1)    │
│                              │                    │
│                              │ in-process         │
│                              ▼                    │
│                        Orchestrator               │
│                              │                    │
│              ┌───────────────┼──────────────┐     │
│              ▼               ▼              ▼     │
│         Docker           llama.cpp       SQLite   │
│         (sandbox)        (127.0.0.1)     + FAISS  │
└───────────────────────────────────────────────────┘
```

**One process, one run at a time.** No job queue, no worker pool, no message broker.

**Justification.** A run saturates GPU and CPU; concurrent runs would contend and make NFR-P3 latency targets meaningless. The tool has exactly one user. Adding a queue would add failure modes without adding capability — and the SRS specifies neither concurrency nor multi-user operation.

The orchestrator runs in a background thread within the service process. Communication is an in-memory queue, not a socket.

## 3.2 Run lifecycle

```
CREATED ──▶ RUNNING ──┬──▶ COMPLETED   (all units verified)
                      ├──▶ PARTIAL     (some verified, some escalated)
                      ├──▶ FAILED      (compilation or harness error)
                      └──▶ CANCELLED   (user requested)
```

**`PARTIAL` is a first-class terminal state, not a failure.** SRS NFR-R1 requires that one unit's failure not prevent others; a run that verifies four units and escalates one has succeeded at its actual job. Collapsing this into `FAILED` would misrepresent the agent's behaviour and would contradict the escalation design, which treats a competent stop as a correct outcome.

## 3.3 Dependency direction

**The API imports the agent. The agent never imports the API.**

Required by NFR-M1, and load-bearing for a practical reason: the CLI must remain fully functional with the service uninstalled and unreachable. If the orchestrator acquires an API dependency, §3.9.4's requirement that the terminal path stands alone is broken, and your Aug 12 fallback dies with it.

**Enforcement:** a test that imports the orchestrator module in an environment where the web framework is not installed. If it raises, the dependency has leaked.

---

# Part IV — Specification

## 4.1 Endpoint surface

Six endpoints. Deliberately minimal — every endpoint is surface area that can violate §2.1.

| Method | Path | Purpose | SRS |
|---|---|---|---|
| `POST` | `/runs` | Start a run. Returns run ID immediately | §3.9.1 |
| `GET` | `/runs/{id}` | Current state, units, metrics | FR-8.2 |
| `GET` | `/runs/{id}/events` | **SSE stream of trace events** | FR-8.1 |
| `GET` | `/runs/{id}/divergences/{unit}` | Full divergence report for a unit | FR-4.4 |
| `POST` | `/runs/{id}/cancel` | Request cancellation | — |
| `POST` | `/runs/{id}/escalations/{unit}/decision` | Accept, reject, or supply a body | FR-7.3 |

**Server-Sent Events, not WebSockets.** The event flow is one-directional — server to client. Control actions are infrequent and fit REST. SSE reconnects automatically with `Last-Event-ID`, which gives resumability for free, and it degrades to a readable stream under `curl`, which matters when debugging at 2 a.m. on Aug 12. A WebSocket would add a second protocol for no gain.

## 4.2 Run creation contract

**Request must carry every parameter affecting output:** COBOL source path, copybook directory, data file path, candidate path or synthesis mode, seed, model name, model digest, maximum repair attempts, and replay flag.

**Response must echo all of them, plus the resolved run ID.**

**Justification — NFR-D1.** Determinism is only meaningful if the parameters that produced a result are recoverable. A run record that omits the seed or the model digest cannot be reproduced, which fails DC-5. The echo is not redundancy; it is the reproducibility record.

The service writes these parameters into the run directory before the first unit executes.

## 4.3 Trace event streaming — GAP

**Requirement:** FR-8.1.

The trace event schema is already specified in SRS §4.7: timestamp, run ID, unit ID, node, action, duration, model calls, tokens in and out, memory-hit flag, outcome, detail.

**Implementation requirements.**

1. **The disk write remains authoritative.** The agent continues to append newline-delimited JSON. The stream is a tee, never a replacement. If the browser disconnects, the trace must be complete on disk — otherwise a crashed browser costs you your metrics.
2. **Events are forwarded verbatim.** No filtering, no aggregation, no reshaping. The frontend receives exactly what the trace file contains. This keeps a single source of truth and satisfies DC-5: the UI and a `cat` of the trace file agree by construction.
3. **Monotonic sequence numbers** per run, used as the SSE event ID, enabling replay from `Last-Event-ID` on reconnect.
4. **Bounded buffer** — retain the most recent 1000 events in memory for late subscribers; older events are served from disk on request.
5. **Backpressure policy:** if a client cannot keep up, drop the client, never block the agent. A slow browser must not slow a run — that would corrupt the timing metrics that R2's comparison depends on.

**Acceptance:** trace file and received event stream are identical, in order, with no gaps, across a full run.

## 4.4 Metrics

**Requirement:** FR-8.2. **Risk:** the backend recomputing them.

Metrics are computed by the **agent**, from the trace, using the same code path the CLI uses. The API serves the resulting object.

**Justification.** SRS §7 traceability makes FR-8.2 the evidentiary basis for the results slide. If the API computed metrics independently, the browser and the CLI could disagree, and the number on the slide would depend on which surface you read it from. There must be exactly one implementation.

**Test:** metrics from `GET /runs/{id}` are byte-identical to metrics from `weaver report {id}`.

## 4.5 Run state persistence — GAP

**Requirement:** NFR-R2 — checkpointed per unit, resumable after interruption.

**Implementation requirements.**

1. After each unit reaches a terminal state, write a checkpoint to the run directory: unit statuses, committed bodies, attempt histories, current metrics.
2. On startup, scan for runs in `RUNNING` state with no live process. Mark them `INTERRUPTED`.
3. Support resumption: reload state, skip committed units, continue from the first incomplete one.
4. **Checkpoint after commit, not before.** A checkpoint written before verification could resume into an unverified state, which would silently violate FR-4.5 — a unit would be treated as verified when it was not.

**Acceptance:** kill the process mid-run; restart; resume; the final result matches an uninterrupted run.

**Cut note.** This is the most likely cut under time pressure. Cutting it is acceptable — but if you cut it, remove NFR-R2 from your conformance claims. Do not claim resumability you have not built.

## 4.6 Error contract

Errors are typed, because the frontend renders three of them differently.

| Class | HTTP | Frontend treatment | SRS |
|---|---|---|---|
| `INVALID_REQUEST` | 400 | Inline field error | — |
| `TOOLCHAIN_MISSING` | 503 | Blocking banner naming the missing tool | §2.4 |
| `INFERENCE_UNAVAILABLE` | 503 | **Degraded-mode banner, run continues** | NFR-R3 |
| `COMPILATION_FAILED` | — | Not an error. A run state with stderr verbatim | FR-3.5 |
| `RUN_NOT_FOUND` | 404 | — | — |
| `INTERNAL` | 500 | Error state with trace ID | — |

**Two entries deserve attention.**

`INFERENCE_UNAVAILABLE` is a **degraded state, not a failure** (NFR-R3). Deterministic repair strategies — padding, scale, sign — require no model. A run with the model down should complete those and escalate the rest. Returning 500 would violate NFR-R3 and would waste a genuinely good demo moment: the agent continuing to work with its model unplugged.

`COMPILATION_FAILED` is **not an HTTP error at all**. Per FR-3.5 it enters the repair loop as a defect class. It is normal agent operation and must appear as run state with the compiler's diagnostics verbatim — never a paraphrase, per the MVP SRS's failure-state requirement.

---

# Part V — Security and Isolation

This section exists because adding a server is the only way this project can start violating constraints it currently satisfies structurally.

## 5.1 Binding and egress — DC-1, NFR-S2

**Requirements.**

1. Bind to `127.0.0.1` explicitly. **Never `0.0.0.0`.** A default bind to all interfaces would place COBOL source and banking-shaped data on the local network, violating NFR-S2 directly.
2. Refuse to start if a non-loopback bind address is configured. Fail closed.
3. No outbound HTTP client in the service. The only network calls in the entire process are to the loopback inference endpoint and the Docker socket.
4. Serve frontend assets from disk. **No CDN links, no web fonts fetched at runtime, no analytics.** A single `<link>` to a font CDN breaks DC-1 and would be found by anyone who runs the AC-11 offline test — which is your own headline demo.

**Verification:** capture traffic for a full run. Only loopback traffic appears.

## 5.2 Inference endpoint validation — §3.9.2

The full SRS requires the configured inference host be validated as loopback at startup, aborting otherwise.

**This must run in the service, not only in the CLI.** A service that skips the check creates a path where the CLI is safe and the UI is not — and it is precisely the UI path judges will watch.

**Verification:** configure a remote inference host; confirm the service refuses to start and names the reason.

## 5.3 Data in transit — NFR-S3

Input data must not be logged verbatim beyond the specific records needed for diagnosis.

Trace events now cross a socket, so:
1. Divergence records carry only the **failing** input record — never the full input set.
2. Bulk data is served on explicit request via the divergences endpoint, not pushed through the event stream.
3. Prompts are never included in trace events. They are cached on disk for replay (FR-8.4) and retrievable by hash if needed for debugging.

## 5.4 Sandbox integrity — NFR-S1, §3.9.3

The backend invokes the orchestrator, which invokes containers. **The backend must not add a host-execution shortcut** for speed, even in development, and must not relax the container flags.

**Verification:** a test asserting the run path never invokes a compiler or program outside a container.

---

# Part VI — Implementation Steps

## Step B1 — Conformance audit **[MUST]**
**Owner:** Dev A · **35 min**

Walk Part II against the actual codebase. Confirm each PASS, confirm each GAP is genuinely absent, and note where each RISK could be introduced.

**Acceptance:** the table is annotated with file and line references. Any status that changes is corrected before building.

**Reason this is first.** Half of these requirements are already satisfied. Building without checking risks reimplementing them in the API layer, which creates the duplicate-source-of-truth problem §1.2 exists to prevent.

---

## Step B2 — Service skeleton with fail-closed binding **[MUST]**
**Owner:** Dev A · **40 min** · **Satisfies:** DC-1, NFR-S2, §3.9.2

1. Create the service module. It imports the agent; the agent imports nothing from it.
2. Bind explicitly to loopback. Refuse any other address.
3. Run the inference loopback validation at startup.
4. Add a health endpoint reporting toolchain and inference availability — this drives the frontend's degraded banner.
5. Add the import-direction test from §3.3.

**Acceptance:** service starts on loopback; refuses a non-loopback bind; refuses a remote inference host; orchestrator imports cleanly without the web framework installed.

---

## Step B3 — Run lifecycle **[MUST]**
**Owner:** Dev A · **60 min** · **Satisfies:** NFR-D1, NFR-R1, §3.9.1

1. Implement create, get, and cancel.
2. Capture and echo all determinism-affecting parameters (§4.2); persist them to the run directory before execution.
3. Implement the five lifecycle states, with `PARTIAL` distinct from `FAILED`.
4. Start the orchestrator on a background thread; return the run ID immediately.
5. Cancellation sets a flag the orchestrator checks between units — never a thread kill, which would leave containers running and state inconsistent.

**Acceptance:** a run starts and returns within 200 ms; a run with one escalation ends `PARTIAL`; cancellation stops cleanly at a unit boundary.

---

## Step B4 — Trace event streaming **[MUST]**
**Owner:** Dev B · **75 min** · **Satisfies:** FR-8.1 · **Closes GAP**

1. Add an in-memory queue the orchestrator publishes to alongside its disk write. Disk remains authoritative.
2. Implement the SSE endpoint with monotonic sequence IDs.
3. Support `Last-Event-ID` replay from the buffer, falling back to disk.
4. Implement drop-slow-client backpressure.
5. Forward events verbatim.

**Acceptance:** trace file and received stream are identical across a full run; a client reconnecting mid-run receives no gaps; a deliberately stalled client is dropped without slowing the run.

**Common failure.** *Events arrive reshaped* — someone added a convenience transform. Remove it; the frontend adapts to the schema, not the reverse.

---

## Step B5 — Divergence and metrics endpoints **[MUST]**
**Owner:** Dev B · **40 min** · **Satisfies:** FR-4.4, FR-8.2

1. Serve the divergence report per unit from the agent's own structure, uncomputed.
2. Serve metrics from the agent's metrics function — the same one the CLI calls.
3. Honour the 50-entry divergence cap while reporting the true total (MVP SRS FR-17).

**Acceptance:** API metrics are byte-identical to `weaver report` output. This is the DC-5 test — run it explicitly.

---

## Step B6 — Escalation decisions **[SHOULD]**
**Owner:** Dev C · **45 min** · **Satisfies:** FR-7.3

1. Accept a decision: accept, reject, or supply a replacement body.
2. **Any accepted body is verified per FR-4.5 before being committed.** A human accepting a body is not evidence it is correct — the oracle is the only authority, and this is the one place a well-meaning API could quietly break DC-4.
3. Write verified decisions to failure memory per FR-6.4.

**Acceptance:** an accepted body that fails verification is rejected and reported as such.

---

## Step B7 — Checkpointing and resume **[SHOULD]**
**Owner:** Dev C · **50 min** · **Satisfies:** NFR-R2 · **Closes GAP**

Per §4.5. Checkpoint after commit, never before.

**Acceptance:** kill mid-run, restart, resume, final state matches an uninterrupted run.

---

## Step B8 — Static asset serving **[MUST]**
**Owner:** Dev A · **25 min** · **Satisfies:** DC-1

1. Serve the frontend bundle from disk.
2. **Self-host fonts.** IBM Plex must be a local file. A CDN reference breaks the offline claim.
3. No runtime external requests of any kind.

**Acceptance:** the full UI loads with all egress blocked.

---

## Step B9 — Conformance validation **[MUST]**
**Owner:** All · **50 min**

Execute Part VII. This is the step that makes "validated against the SRS" a true statement rather than a claim.

---

# Part VII — Validation

## 7.1 Requirement tests

| SRS ID | Test | Pass condition |
|---|---|---|
| FR-8.1 | Full run, capture stream, diff against trace file | Identical, ordered, no gaps |
| FR-8.2 | Compare API metrics to `weaver report` | Byte-identical |
| FR-8.4 | Start run with replay flag | Zero inference calls |
| FR-4.5 | Submit an accepted-but-wrong body via B6 | Rejected on verification |
| FR-7.3 | Submit a decision, inspect memory | Written only after verification |
| NFR-R1 | Run with a forced escalation | Independent units still complete; state `PARTIAL` |
| NFR-R2 | Kill and resume | Final state matches uninterrupted run |
| NFR-R3 | Stop inference, start run | Deterministic repairs proceed; degraded status; no 500 |
| NFR-S1 | Audit subprocess invocations | No host execution path |
| NFR-S3 | Inspect all events for a run | No full input set; no prompts |
| NFR-M1 | Import orchestrator without web framework | Imports cleanly |
| NFR-D1 | Two runs, same parameters | Identical output; parameters echoed |
| DC-4 | Audit API for comparison logic | None present |
| DC-5 | Every API-exposed number | Obtainable from CLI |

## 7.2 The offline test — DC-1, NFR-S2

**This is the blocking test.** It is also your Aug 12 stage moment (AC-11), so it must be rehearsed, not merely passed once.

1. Block all non-loopback egress with a firewall rule, or physically disconnect.
2. Start the service. Load the UI in a browser. Run a full migration.
3. Confirm completion, correct rendering, and correct fonts.
4. Capture traffic throughout; confirm loopback only.

**Fail conditions to watch for:** fonts fall back because a CDN was referenced; a favicon or source map 404s to an external host; the UI hangs waiting on an analytics call.

## 7.3 Non-regression

The CLI must remain fully functional with the service stopped. Run the full MVP verification via CLI with no service process and confirm 113 divergences. If this breaks, §3.9.4 is violated and your Aug 12 fallback no longer exists.

---

# Part VIII — Traceability

| SRS requirement | Implementing step | Validating test |
|---|---|---|
| FR-3.5 | B3 (state), B4 (event) | §7.1 |
| FR-4.4 | B5 | §7.1 |
| FR-4.5 | B6 | §7.1 |
| FR-6.4 | B6 | §7.1 |
| FR-7.3 | B6 | §7.1 |
| FR-8.1 | B4 | §7.1 |
| FR-8.2 | B5 | §7.1 |
| FR-8.4 | B3 | §7.1 |
| §3.9.1 | B3 | §7.3 |
| §3.9.2 | B2 | §7.1 |
| §3.9.4 | B2, B8 | §7.3 |
| NFR-R1 | B3 | §7.1 |
| NFR-R2 | B7 | §7.1 |
| NFR-R3 | B2, B4 | §7.1 |
| NFR-S1 | B2 | §7.1 |
| NFR-S2 | B2, B8 | §7.2 |
| NFR-S3 | B4 | §7.1 |
| NFR-D1 | B3 | §7.1 |
| NFR-M1 | B2 | §7.1 |
| DC-1 | B2, B8 | §7.2 |
| DC-4 | §1.2 discipline | §7.1 |
| DC-5 | B5 | §7.1 |

**No requirement is implemented in more than one place**, and every requirement has a test. Both properties should hold after any change; if a second implementation appears, §1.2 has been violated.

---

# Part IX — Time and Risk

## 9.1 Budget

| Step | Hours | Priority |
|---|---|---|
| B1 Audit | 0.6 | MUST |
| B2 Skeleton | 0.7 | MUST |
| B3 Lifecycle | 1.0 | MUST |
| B4 Streaming | 1.25 | MUST |
| B5 Endpoints | 0.7 | MUST |
| B6 Escalation | 0.75 | SHOULD |
| B7 Checkpointing | 0.85 | SHOULD |
| B8 Assets | 0.4 | MUST |
| B9 Validation | 0.85 | MUST |

**MUST: 5.5 h · Full: 7.1 h.** One developer, Aug 11. Steps B4 and B5 parallelise with B3.

## 9.2 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Domain logic leaks into the API** | **High** | §1.2 test — every API number obtainable from the CLI. Check at B5 and B9 |
| Font or asset CDN reference | Medium | B8; caught by §7.2. This is the most common way a "fully offline" claim quietly fails |
| Event schema drift between agent and frontend | Medium | Forward verbatim (B4); frontend adapts to SRS §4.7 |
| Slow client stalls the run | Medium | Drop-client backpressure (B4). Would corrupt timing metrics |
| Agent acquires an API dependency | Low | Import test at B2; would break the CLI fallback |
| Checkpointing consumes the window | Medium | B7 is SHOULD. Cut it — and remove NFR-R2 from conformance claims if you do |

## 9.3 Cut order

1. **B7** checkpointing — remove NFR-R2 from claimed conformance
2. **B6** escalation decisions — render escalations read-only
3. Divergence pagination — serve the 50-entry cap only

**Never cut:** B2 (binding and validation), B4 (streaming — the frontend has nothing without it), B8 (self-hosted assets), B9 (validation, which is what makes this document's title true).

---

# Part X — Conformance Statement

On completion of B9, the following is claimable and defensible:

> The backend service satisfies all applicable requirements of LegacyWeaver SRS v1.0. It introduces no correctness logic: every value it exposes is produced by the agent and is independently obtainable from the command line. It binds to loopback, validates its inference endpoint as loopback at startup, serves all assets from disk, and makes no outbound network call. A complete migration executes through the browser interface with all non-loopback egress blocked.

**Do not make this statement before §7.2 passes.** The offline claim is the most load-bearing assertion in the project, it is the one you demonstrate live on Aug 12, and it is the easiest to break with a single `<link>` tag.
