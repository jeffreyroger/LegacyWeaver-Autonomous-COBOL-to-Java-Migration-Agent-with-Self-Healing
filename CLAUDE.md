# CLAUDE.md — Working rules for LegacyWeaver

These rules are binding for every session working in this repository.

## The governing documents

- [docs/specs/MVP_SRS.md](docs/specs/MVP_SRS.md) — what must be true (requirements, acceptance criteria) for the MVP (Phase 1).
- [docs/specs/MVP_IMPLEMENTATION_PLAN.md](docs/specs/MVP_IMPLEMENTATION_PLAN.md) — how and in what order to build the MVP (phases A–I, owners, acceptance tests).
- [docs/specs/AGENT_LAYER_PLAN.md](docs/specs/AGENT_LAYER_PLAN.md) — how and in what order to build the agent layer (Phase 2: phases J–T — local inference, deterministic scaffold, synthesis, repair loop, failure memory, orchestrator, escalation, measurement, memory demo, demo prep).
- [docs/specs/BACKEND_PLAN.md](docs/specs/BACKEND_PLAN.md) — how to build the local run service (transport/lifecycle layer between agent and frontend) in `backend/`. Its own stated precondition is "MVP complete · agent layer complete." The backend contains no domain logic: it must never compare output, classify defects, or decide verification — any value the API returns must be independently reproducible via `weaver verify` on the command line, or the backend is doing something it should not (SRS DC-4, DC-5).

**Before making any implementation decision, re-check the relevant document(s).**
Do not improvise scope, architecture, numbers, or sequencing that isn't in
them. If something is genuinely unspecified, say so explicitly rather than
inventing it.

## Phase 2 is now authorized

MVP Phase 1 (A–I) is complete — oracle verified, differential runner
reporting 132/201 against this repo's own fixture (see rule 6 below), zero
false positives. Per explicit user direction on 2026-08-07, work on the agent
layer (`AGENT_LAYER_PLAN.md`, phases J–T: synthesis, repair loop, failure
memory, orchestrator) is now in scope and authorized. The prior blanket
prohibition on starting this work no longer applies. All hard rules below
that are specific to the MVP harness (comparison contract, deterministic
classification, exact-decimal arithmetic, layout-as-data, offline operation)
remain binding for Phase 2 as well — the agent layer is built *around* that
harness, not as a replacement for it.

## Hard rules

1. **Follow each plan's phase order.** MVP: A, B, C, D, E, F, G, H, I, per the
   critical path (`MVP_IMPLEMENTATION_PLAN.md` "Critical path" section).
   Agent layer: J, K, L, M, N, O, P, Q, R, S, T, per `AGENT_LAYER_PLAN.md`.
   Do not start a step until its prerequisites' acceptance tests actually
   pass. Do not pull forward work from a later phase.

2. **Every step must pass its stated acceptance test before moving on.**
   Acceptance tests are not optional checkpoints — they are the definition of
   done for that step.

3. **The comparison contract is absolute (FR-10, DC-4).** Byte-for-byte only.
   The only permitted normalisation is line-ending conversion. No tolerance,
   threshold, heuristic, or model may ever participate in the equivalence
   determination. Do not add one "to make the numbers look better" — this is
   the project's central thesis and it must not be relaxed, ever, under any
   pressure.

4. **Classification is deterministic only (FR-13, DC-4).** No language model
   in the classification path. Rule order matters: PADDING, SIGN, SCALE,
   TRUNCATION, CONTROL_FLOW, UNKNOWN — most specific first.

5. **Exact decimal arithmetic only (DC-3).** Use Python `decimal.Decimal`
   throughout the harness. Never binary floating point for money or for
   comparison logic. (Floating point is deliberately used *inside the
   baseline candidate* — that is a planted defect, not a harness bug.)

6. **Known target numbers are load-bearing, not incidental.** Record length:
   39 bytes (input), 42 bytes (report line, corrected — see below). Input
   records: 200. Golden output: 200 detail lines + 1 totals line (201 lines).

   The runbook's own reference numbers (checksum `149ff767b1...`, divergence
   `113 of 200`) come from the original spec authors' fixture and generator
   source, which this repo does not have — only their *description* of the
   encoding rules. This repo's independently-built oracle and generator
   necessarily produce different-but-internally-consistent numbers. **This
   repo's actual load-bearing numbers, once established, replace the
   runbook's for all subsequent steps:**

   - Golden output checksum: `833afd92bd7879187d450107f9f572d3bdbbdcc0a44804d363c264df3d7461b1`
     (see `fixtures/data/expected/golden_interest.out.sha256`) — reconfirmed
     by 10 consecutive independent runs of the compiled oracle.
   - Predicted oracle-vs-baseline divergence (Step C4), **among the 200
     detail records only**: **131 of 200** (see `fixtures/predict_divergence.py`
     output — 131 interest-value mismatches, 28 of them also carrying a
     balance-sign mismatch). `predict_divergence.py` deliberately only
     iterates the 200 input records; it does not model the derived totals
     line.
   - Phase D's differential runner compares all **201** report lines (200
     detail + 1 totals) and independently reports **132**: the same 131
     detail-line divergences C4 predicted, plus one further divergence on
     the totals line itself (`TL-TOTAL`) — the baseline's float summation
     of 200 already-wrong interest values necessarily disagrees with the
     oracle's exact-decimal total. This is not drift from 131; it is 131
     plus one additional, independently-explained divergence outside
     C4's prediction scope. Confirmed by isolating record index 200 in
     the runner's output on 2026-08-07.
   - `tests/test_acceptance.py::test_full_pipeline_against_real_fixture`
     asserts `total_records == 201` and `divergence_count == 132`; treat
     132 (not 131) as the number Phase D/F/H must reproduce end-to-end.

   If an implementation produces a number that matches neither the
   runbook's reference NOR this repo's own previously-established number,
   the implementation is suspect first — re-read the relevant step before
   concluding a target is wrong. A one-time recomputation of this repo's
   own target (as happened after the Step B4 edit-mask bugfix) is
   legitimate; drifting silently between runs is not.

   **Report-line layout was corrected after Step B4/B5 review**: the
   original `-(8)9.99` / `-(6)9.99` edit-mask pictures for RL-BALANCE /
   RL-INTEREST were one print position too narrow to hold a
   maximum-magnitude value together with its sign, silently dropping the
   leading digit on the two extreme boundary records. Widened to
   `-(9)9.99` / `-(7)9.99` (see `weaver/layout.py` REPORT_LAYOUT,
   `docs/specs/oracle_hand_verification.md`). Report line is now 42 bytes,
   not 40.

7. **Blocking gates cannot be skipped or softened (SRS §6.3, runbook "critical
   path").** AC-2 (golden output determinism), AC-3 (independent hand
   verification), AC-9 (self-comparison zero false positives), AC-12
   (fresh-clone reproducibility). Steps B4, B5, C3, D5, D6, H3, I1, I3 are
   never cut, even under time pressure (runbook "Cut order under time
   pressure").

8. **GnuCOBOL must be 3.x, not 2.x.** Version 2.x silently produces different
   arithmetic and invalidates the golden output (SRS §2.4, runbook Step A1).
   Verify the version before trusting any COBOL-derived result.

9. **Layouts are data, not code (NFR-14).** Comparison and classification
   code must not hardcode offsets — a second fixture must require no code
   change to those modules.

   **As of Phase V (2026-08-12) layouts are *derived* data.**
   `weaver/cobol/` parses the DATA DIVISION and produces the field tables,
   condition names, working-storage tables, file names and main-loop
   wiring that `weaver/layout.py` and the six `*_layout.py` / `*_spec.py`
   pairs previously declared by hand. Binding consequences:

   - Parsing happens **once, upstream, in `weaver/cobol/`, and emits data.**
     `weaver/agent/scaffold.py` must keep reading only a `ScaffoldSpec` and
     never COBOL source text (AGENT_LAYER_PLAN.md K2).
   - The hand-written tables are retained as the parser's **regression
     oracle**, asserted equal across all six fixtures in
     `tests/test_cobol_frontend.py`. Do not delete them to "remove
     duplication" — they are the only independent check that the parser is
     right, and the reason the load-bearing numbers are unchanged by
     construction rather than by re-measurement.
   - `weaver/agent/program_profiles.py` declares **artefact locations only**
     (where a golden output or reference body lives). Anything that is a
     fact about the COBOL — layouts, output filename, `ScaffoldSpec`,
     paragraph id — must be derived, never re-declared there.
   - A program that is present but outside the frontend's declared scope
     **raises**. Never restore a `None`/fallback path: it resolves to
     interest.cob's layouts and produces a confident wrong answer.
   - The synthesis prompt is hashed into the model cache key (Step J4), so
     text derived from the parsed program is cache-affecting.
     `tests/test_cobol_frontend.py` pins the rendering.

10. **Offline and credential-free, always (DC-1, NFR-8, NFR-10).** No network
    call, no API key, no account, at any point in a verification run.

    **Scoped CI exception (2026-08-12):** local, CLI, backend, and frontend
    runs remain fully offline exactly as above — the default inference
    provider is local Ollama and this is unchanged. The `.github/workflows/`
    GitHub Action that auto-migrates files pushed to `input/` is the sole
    exception: GitHub-hosted runners have no local model runtime, so that
    workflow only sets `WEAVER_INFERENCE_PROVIDER=groq` and calls Groq's
    hosted API with a `GROQ_API_KEY` repo secret (see
    `weaver/agent/inference.py`'s `provider="groq"` path). Nothing else may
    read this env var or relax the offline default.

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

    **Scoped local WSL delegation exception (2026-08-20,
    SUBPROGRAM_VERIFICATION_PLAN.md Phase X3):** `weaver/agent/subprogram_verify.py`
    may route `cobc` invocations through `wsl -e bash -lc` instead of calling
    it directly. This is opt-in only (`WEAVER_COBC_VIA_WSL=1` in the
    environment) and only ever takes effect when no native `cobc` is on
    PATH — a machine with native `cobc` (every CI runner) never touches this
    path regardless of the env var. It exists solely because this
    project's Windows dev machine has no native GnuCOBOL toolchain; it
    changes nothing about what gets verified — the same real,
    currently-compiled subprogram source is compiled and run either way,
    only the shell wrapper differs. Nothing else may read
    `WEAVER_COBC_VIA_WSL`, and no other module may gain a WSL branch
    without its own disclosed exception here.

    **Extended 2026-08-23 to the main `weaver verify` path:**
    `weaver/cli.py`'s `_compile_oracle` and `weaver/execution.py`'s
    `run_oracle` gained the identical opt-in WSL branch (same env var, same
    native-`cobc`-absent gate), so `weaver verify` is runnable end-to-end
    on this machine — compile *and* execute the oracle binary via
    `wsl -e bash -lc`, same compiled artefact either way, only the shell
    wrapper differs. `weaver/agent/mocked_verify.py` already reused this
    exact pattern from `subprogram_verify.py` before this date; this is the
    same reuse extended to the harness's primary entry point rather than a
    new mechanism.

    **Scoped live-connector exception (2026-08-20, migration-framework-spec.md
    Section 4.2, Phase Z2):** `tests/test_connectors_live.py` may start local
    Docker containers (`postgres`, `rabbitmq`) and make real network calls to
    them, and may compile/run `weaver/agent/connector_codegen.py`'s generated
    `RabbitMqQueue.java`/`PostgresDataSource.java` adapters against a jar
    directory named by `WEAVER_CONNECTOR_CLASSPATH`. This is opt-in only
    (`WEAVER_LIVE_CONNECTORS=1` in the environment) and is a separate,
    explicitly-invoked test lane — `weaver verify`/`weaver migrate`/`weaver
    connectors` never read this flag and never open a socket. Every
    parity-gate verification binds `OfflineAdapters.java` only (Phase Z1's
    deterministic `MockMap`, reused verbatim). Nothing else may read
    `WEAVER_LIVE_CONNECTORS` or `WEAVER_CONNECTOR_CLASSPATH`.

11. **Baseline defects are declared, not hidden (FR-8).** Any change to
    `baseline/Baseline.java` must keep its header comment accurate — it must
    enumerate every deviation the file actually contains, no more, no less.

12. **Scope stays disclosed (FR-20, DC-6).** Do not let the README, code
    comments, or any output claim a component works before it has passed its
    own acceptance test in `AGENT_LAYER_PLAN.md`. Anything not yet built
    (e.g. sandboxing, if never scoped into a phase) stays explicitly marked
    as not implemented rather than implied.

13. **Run parameters live in `RunSpec` and must actually take effect.**
    `weaver/agent/runspec.py` is the single definition of what parameters
    constitute a run, one field per SRS §3.9.1 `migrate` flag. Before
    2026-08-07, `Orchestrator.scaffold_path` was accepted and never read,
    the backend's required `data_file` was written into `params.json`
    without influencing the run (DC-5/NFR-D1), and `max_repairs`/`seed`/
    `replay` had no caller hook at all. Never add a run parameter that is
    accepted but not threaded to the code that consumes it;
    `tests/test_param_plumbing.py` guards this.

## Before starting any step

1. Read the corresponding runbook step (owner, prerequisites, procedure,
   acceptance test, common failures) in full.
2. Confirm its prerequisites' acceptance tests actually pass — don't assume.
3. Implement exactly what the step asks for. Do not pull forward work from a
   later phase.
4. Run the acceptance test and show the result before declaring the step
   done.

## When something seems to call for a judgment outside the plan

Stop and check the SRS and runbook again — most "judgment calls" are already
answered there (definitions in SRS §1.3, rules in §3, constraints in §2.7).
If it is truly unspecified, flag it explicitly rather than silently deciding.
