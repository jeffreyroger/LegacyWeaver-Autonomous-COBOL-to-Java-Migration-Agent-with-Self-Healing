# LegacyWeaver MVP — Implementation Runbook

**Document type:** Execution plan
**Version:** 1.0 · 07 August 2026
**Deadline:** 8 August 2026, 21:00 IST (submit) / 23:59 IST (hard)
**Working window:** ~30 hours
**Team:** 4 developers (A, B, C, D)

---

## How to use this document

Every step has the same structure:

> **Objective** — what this step achieves and why it exists
> **Owner / Duration** — who does it, how long it should take
> **Prerequisites** — what must be true before starting
> **Procedure** — numbered actions
> **Acceptance test** — the objective check that proves the step is done
> **Common failures** — what goes wrong and how to fix it

**Do not start a step until its prerequisites pass their acceptance tests.** The dependency chain is real: every downstream step assumes the oracle is trustworthy, and if it isn't, you will spend hours debugging the wrong component.

Steps are labelled **[MUST]** (blocks submission) or **[SHOULD]** (improves submission, cut if late).

---

## Phase A — Environment (Aug 7 evening, 45 min, all four in parallel)

### Step A1 — Install the COBOL toolchain **[MUST]**

**Objective.** Every developer must be able to compile and run COBOL locally. Without this, only one person can work on the oracle and the whole project bottlenecks on them.

**Owner:** All four · **Duration:** 15 min

**Procedure.**
1. On Ubuntu/Debian: install the `gnucobol` package via apt. On macOS: install via Homebrew. On Windows: install WSL2 with Ubuntu first, then follow the Ubuntu path — do not attempt a native Windows GnuCOBOL build tonight.
2. Confirm the compiler binary `cobc` is on `PATH`.
3. Confirm the version is 3.x. Version 2.x has different default arithmetic behaviour and will produce different golden output, which will silently break the whole comparison later.
4. Record the exact version string in a shared team note.

**Acceptance test.** Every developer runs the version command and reports 3.x in the team chat. **All four must confirm before Phase B begins.**

**Common failures.**
- *Package not found* — enable the `universe` repository on Ubuntu, then update the package index.
- *Version 2.x installed* — this is the single most dangerous environment problem in this project, because it fails silently rather than loudly. Build 3.x from source or use the Docker path in Step A4.

---

### Step A2 — Install the Java toolchain **[MUST]**

**Objective.** Compile and run the candidate translation.

**Owner:** All four · **Duration:** 10 min

**Procedure.**
1. Install a JDK (not a JRE) version 17 or later. Verify that both `java` and `javac` exist — a JRE-only install provides `java` but not `javac`, and this is a very common trap.
2. Confirm both are on `PATH`.

**Acceptance test.** `javac` reports a version ≥ 17. Note specifically: the presence of `java` alone does **not** pass this test.

**Common failures.**
- *`javac: command not found` while `java` works* — you have a JRE. Install the full JDK package.

---

### Step A3 — Install Python and set up the project **[MUST]**

**Objective.** The agent harness runs on Python. `decimal.Decimal` is required because it models COBOL fixed-point arithmetic exactly; floating point would introduce comparison errors of its own and destroy the experiment.

**Owner:** All four · **Duration:** 10 min

**Procedure.**
1. Confirm Python 3.11 or later.
2. Create a virtual environment at the project root and activate it.
3. Install only `rich` for now. Add nothing else until Phase F — every dependency added tonight is a dependency that can break on a teammate's machine tomorrow.

**Acceptance test.** Python reports 3.11+, and importing `decimal` and `rich` succeeds inside the virtual environment.

---

### Step A4 — Prepare the Docker fallback **[SHOULD]**

**Objective.** Insurance. If any developer's native toolchain fails, they must still be able to work rather than sit idle for a day.

**Owner:** Dev C · **Duration:** 20 min

**Procedure.**
1. Write a Dockerfile based on Ubuntu 24.04 that installs GnuCOBOL, a JDK, and Python.
2. Build the image and tag it.
3. Document the volume-mount command that maps the project directory into the container.
4. Post both the image name and the exact run command in the team chat.

**Acceptance test.** A developer whose native install failed can compile the fixture inside the container.

**Note.** This same image becomes the sandbox runtime after Aug 8 (SRS §3.9.3 of the full specification), so the effort is not throwaway.

---

## Phase B — The Oracle (Aug 7 evening, 2 hours)

This phase is the foundation. **If the oracle is wrong, everything downstream is meaningless** — you would be measuring divergence against a false standard, and every conclusion in your deck would be invalid.

### Step B1 — Understand the record layout before touching anything **[MUST]**

**Objective.** Every subsequent step depends on byte offsets. Getting them wrong produces divergences that look like translation bugs but are actually parsing bugs — the most expensive class of error to debug because it points you at the wrong component.

**Owner:** Dev A · **Duration:** 20 min

**Procedure.**
1. Read the copybook and construct a byte-offset table by hand, on paper. For each field record: name, PIC clause, starting byte, byte width.
2. Apply these rules while doing it:
   - A `PIC X(n)` field occupies exactly n bytes.
   - A `PIC 9(n)V9(m)` field occupies n+m bytes. **The `V` is an implied decimal point and occupies zero bytes.** This is the single most common misunderstanding in COBOL data handling.
   - A field declared `SIGN IS TRAILING SEPARATE` occupies one **additional** byte for the sign character.
   - A `REDEFINES` field starts at the **same offset as its target** and does not extend the record.
3. Sum the widths and confirm the total record length.
4. Have a second developer independently derive the same table and compare. Discrepancies here are cheap to fix now and very expensive to fix on Aug 11.

**Acceptance test.** Two independently derived offset tables agree, and both give a total record length of **39 bytes**.

**Common failures.**
- *Counting `V` as a byte* — produces an off-by-one on every field after the first numeric one, cascading through the entire record.
- *Appending the `REDEFINES` group* — produces a record length of 43 instead of 39 and every field after `AR-FLAGS` misaligns.

---

### Step B2 — Compile the fixture **[MUST]**

**Objective.** Produce the oracle binary.

**Owner:** Dev A · **Duration:** 15 min · **Prerequisites:** A1, B1

**Procedure.**
1. Invoke the COBOL compiler in executable mode.
2. Pass the fixed-format flag. The fixture uses traditional column-sensitive layout where columns 1–6 are the sequence area, column 7 is the indicator, columns 8–11 are Area A, and 12–72 are Area B. Compiling it as free-format produces a wall of confusing syntax errors.
3. Pass the copybook directory as an include path so the `COPY` statement resolves.
4. Direct output to a build directory that is git-ignored.

**Acceptance test.** The binary exists and is executable. Note that GnuCOBOL emits a `_FORTIFY_SOURCE` redefinition warning on some systems — this is benign and does not indicate a problem.

**Common failures.**
- *Copybook not found* — the include path is wrong, or the filename case does not match. Linux is case-sensitive.
- *Syntax errors across many lines* — you omitted the fixed-format flag.

---

### Step B3 — Understand and verify the data generator **[MUST]**

**Objective.** Produce deterministic test input. Determinism is non-negotiable: if the input changes between runs, your divergence count changes, and every number in your deck becomes unreproducible.

**Owner:** Dev B · **Duration:** 30 min · **Prerequisites:** B1

**Procedure.**
1. Read the generator and confirm it encodes each field per the Step B1 offset table. In particular confirm:
   - Balance is written as an 11-digit zero-padded integer of **paise**, followed by a separate `+` or `-` sign character. There is no decimal point in the file.
   - Rate is written as a 6-digit integer scaled by 100000, again with no decimal point.
   - Flags occupy 4 bytes, where byte 1 is the dormant indicator accessed through the `REDEFINES` overlay.
2. Confirm the random seed is fixed at a constant.
3. Confirm the record composition covers each planted trap:

| Group | Count | Trap exercised |
|---|---|---|
| Truncation-boundary balances | 40 | T1 — result lands on a third decimal place |
| Ordinary savings | 50 | Baseline correctness |
| Negative balances | 25 | T6 — trailing separate sign |
| Dormant accounts | 25 | T3 — REDEFINES overlay |
| Premium accounts | 30 | T4 — 88-level tier, rate re-truncation |
| Hold flag | 15 | T3 — second byte of overlay |
| Boundary values | 15 | Zero, maximum, minimum, zero-rate |

4. Run the generator twice into different files and compare them byte-for-byte.

**Acceptance test.** 200 records written, every line exactly 39 characters, and two runs produce byte-identical files.

**Common failures.**
- *Lines are not 39 characters* — a field is being formatted with the wrong width. Print the length of the first record and compare against the Step B1 table field by field.
- *Files differ between runs* — the seed is not being applied, or a set/dict iteration order is leaking into output.

---

### Step B4 — Produce the golden output **[MUST]**

**Objective.** Establish ground truth. This file is the specification against which everything is judged for the rest of the project.

**Owner:** Dev A · **Duration:** 20 min · **Prerequisites:** B2, B3

**Procedure.**
1. Place the generated data file in the same working directory as the oracle binary — the program opens it by relative filename.
2. Run the binary.
3. Inspect the output: it should contain 200 detail lines plus one totals line.
4. Run the binary ten consecutive times, computing a checksum of the output each time.
5. Copy the output to the expected-results directory under a name that marks it as golden, and commit it.

**Acceptance test.** Ten consecutive runs produce identical checksums. The reference value is `149ff767b1c53f95f73bf6343e8c224852a364f1cf574208ce17bb0c1c1a92a4`.

**Common failures.**
- *File-not-found at runtime* — the data file must be in the process working directory, not next to the source.
- *Checksums differ between runs* — something non-deterministic has crept into the fixture. Check for date, time, or random functions. There should be none.
- *Checksum differs from the reference* — your GnuCOBOL is a different version, or your data generator differs. Resolve this now. Do not proceed with a mismatched baseline.

---

### Step B5 — Hand-verify five records **[MUST]**

**Objective.** Prove independently that the oracle computes what you think it computes. Machine agreement with itself proves nothing. This is the step teams skip and later regret, because it is the only thing standing between you and confidently presenting a wrong number to judges.

**Owner:** Dev B · **Duration:** 25 min · **Prerequisites:** B4

**Procedure.**
1. Choose five records deliberately: one ordinary savings, one premium, one dormant, one negative balance, one boundary value.
2. For each, decode the input line by hand using the Step B1 offset table into balance, rate, type, and flags.
3. Compute the expected interest with a calculator, applying the program's stated logic:
   - If premium, multiply the rate by 1.15 and **truncate the result to five decimal places** — the working-storage field only holds five, so the extra digit is discarded before it is ever used.
   - If dormant, interest is zero regardless of balance.
   - Otherwise, compute balance × applied-rate ÷ 365 and **truncate to two decimals**, discarding the remainder. Do not round.
4. Compare against the corresponding line of golden output.
5. Record all five calculations in a shared document. This becomes your evidence when a judge asks how you know the oracle is right.

**Acceptance test.** All five hand calculations match the golden output exactly.

**Common failures.**
- *Off by one paisa* — you rounded where COBOL truncates. This is the exact error your entire project exists to catch, so encountering it here is instructive rather than alarming.
- *Premium record off by more than a paisa* — you forgot the intermediate truncation of the rate itself. There are two truncations in the premium path, not one.

---

## Phase C — The Baseline Candidate (Aug 7 night, 1.5 hours)

### Step C1 — Understand what you are building and why **[MUST]**

**Objective.** The baseline is the control arm of an experiment. Its purpose is to represent what unconstrained translation produces, so that the divergence count measures something real.

**Owner:** Dev B · **Duration:** 10 min

**Reasoning to internalise before writing anything.** You are deliberately building something wrong. This is scientifically legitimate *only if you state it openly*. A hidden strawman is cheating and a judge will catch it. A declared control arm is rigour and a judge will respect it.

The baseline must be wrong in the ways real translations are wrong — not in invented ways. Each defect must be one that an unconstrained translator plausibly produces:

| Defect to introduce | Why it is realistic |
|---|---|
| IEEE-754 floating point for money | The single most common mistake in financial code translation |
| Round-half-up instead of truncate | Java's conventional default; COBOL's default is the opposite |
| Flags compared as a 4-character string | The `REDEFINES` overlay is invisible unless you parse the data division |
| Sign character parsed as part of the number | Trailing-separate sign is unfamiliar outside COBOL |

**Acceptance test.** Dev B can state, in one sentence each, why every planted defect is realistic rather than contrived.

---

### Step C2 — Specify the baseline before writing it **[MUST]**

**Objective.** Avoid the failure mode where the baseline accidentally gets the answer right and your divergence count collapses to zero the night before submission.

**Owner:** Dev B · **Duration:** 20 min · **Prerequisites:** C1

**Procedure.** Write a short specification covering:
1. **Input parsing** — read the file line by line, slice fields by the Step B1 offsets. Parse balance by taking the 11 digit characters and dividing by 100, using a floating-point type. Parse the sign character separately, or deliberately ignore it, to exercise T6.
2. **Interest computation** — floating-point multiply and divide, then round half-up to two decimals.
3. **Dormant handling** — compare the whole 4-character flags field against the literal `"Y"`. Because the field is four bytes and contains `"Y   "`, this comparison never matches, so dormant accounts incorrectly accrue interest. This reproduces T3 exactly.
4. **Output formatting** — produce a fixed-width line matching the report layout, but format numbers using a general-purpose numeric formatter rather than replicating the COBOL edit mask. This exercises T5.
5. **Header comment** — the file must open with a comment stating that it is a deliberately unconstrained baseline representing typical LLM translation output, and that it is the control arm of a measurement.

**Acceptance test.** The specification is written down and reviewed by a second developer before implementation begins.

---

### Step C3 — Implement and compile the baseline **[MUST]**

**Owner:** Dev B · **Duration:** 45 min · **Prerequisites:** C2, A2

**Procedure.**
1. Implement to the Step C2 specification.
2. Compile it.
3. Run it against the same input file in a separate working directory so it cannot overwrite the golden output.
4. Eyeball the first few lines against the golden output. You should see visible differences.

**Acceptance test.** The baseline compiles, runs to completion, produces 201 output lines, and its output differs from golden.

**Common failures.**
- *Output is identical to golden* — your baseline is accidentally correct. Check that you used floating point and half-up rounding rather than exact decimal arithmetic.
- *Fewer than 201 lines* — the totals line is missing, or a loop terminated early.
- *Program crashes on negative balances* — the trailing sign character is being fed into a numeric parser. This is a real defect, and it belongs in the report rather than being fixed.

---

### Step C4 — Establish the expected divergence count **[MUST]**

**Objective.** Know the number before you build the tool that measures it. If your tool reports a different number, you will immediately know the tool is wrong rather than assuming the number is interesting.

**Owner:** Dev B · **Duration:** 15 min · **Prerequisites:** C3

**Procedure.**
1. Write a short throwaway script that reads the input file, applies COBOL semantics (exact decimal, truncate) and naive semantics (round half-up, ignore the flag overlay) to each record, and counts how many differ.
2. Break the count down by cause.

**Acceptance test.** The predicted count is **113 of 200** — 87 from truncation, 26 from the REDEFINES overlay. This is your target. Phase D is complete when the differential runner independently reports the same number.

---

## Phase D — The Differential Runner (Aug 8 morning, 2.5 hours)

This is the core intellectual contribution of the project. Everything else is supporting infrastructure.

### Step D1 — Design the comparison contract **[MUST]**

**Objective.** Decide precisely what counts as a divergence, and write it down, before implementing.

**Owner:** Dev C · **Duration:** 20 min

**The rules, which must not be relaxed later.**
1. Comparison is **byte-for-byte**.
2. The **only** permitted normalisation is line endings (CRLF to LF). Nothing else.
3. Trailing whitespace differences are **genuine defects**, not noise. A COBOL report that pads to a fixed width and a Java report that does not are not equivalent, because downstream systems parse by column.
4. Exit codes must match.
5. A candidate is verified **if and only if** divergence count is zero and exit codes match.
6. **No heuristic, threshold, tolerance, or language model may participate in this determination.** The moment you introduce a tolerance to make the numbers look better, the oracle stops being an oracle and the project loses its thesis.

**Acceptance test.** The six rules are written into the module's docstring and reviewed by Dev A.

---

### Step D2 — Implement dual execution **[MUST]**

**Objective.** Run both programs against byte-identical input.

**Owner:** Dev C · **Duration:** 40 min · **Prerequisites:** D1, B4, C3

**Procedure.**
1. Create a fresh temporary working directory per run so that neither program can see or overwrite the other's output.
2. Copy the same input file into each working directory. Copy it — do not regenerate it. Regenerating introduces the possibility of divergent input, which would invalidate the comparison.
3. Execute the oracle binary in its directory as a subprocess. Capture stdout, stderr, exit code, and read back the output file.
4. Execute the Java candidate in its directory. Capture the same four artefacts.
5. Impose a wall-clock timeout of 30 seconds on each. An infinite loop in generated code must not hang the harness.
6. Handle the case where a program produces no output file at all — this is a divergence, not a crash of the harness.

**Acceptance test.** Both programs execute and return their output line lists, exit codes, and stderr. Deliberately introduce an infinite loop into a copy of the candidate and confirm the timeout fires cleanly.

---

### Step D3 — Implement field resolution **[MUST]**

**Objective.** Convert a raw byte difference into a diagnosis. This is what makes the repair loop possible on Aug 11 — a repair prompt containing "byte 30 differs" is useless, while "`DL-INTEREST` is off by ₹0.01 on this specific input record" is directly actionable.

**Owner:** Dev C · **Duration:** 40 min · **Prerequisites:** D2

**Procedure.**
1. Build a layout table for the **report** line — distinct from the input record layout of Step B1. Derive the offsets from the detail-line declaration in the COBOL source: identifier, type, balance, interest, flag, with their start positions and widths.
2. For each pair of lines that differ, walk the layout table and find the first field whose slices differ. That field is the divergence site.
3. Record: record index, byte offset, field name, oracle value, candidate value.
4. Where both values parse as numbers, compute and record the numeric delta. This is what drives classification in Phase E.
5. Record the **input line that produced this output line**. Without this, no repair is possible.
6. Cap the stored divergence list at 50 entries while continuing to count all of them. A 200-entry JSON blob is unreadable in a demo; the count is what matters, the examples are illustration.

**Acceptance test.** Given the golden output and a candidate with a deliberately altered interest value on one line, the runner reports exactly one divergence, correctly names the interest field, correctly reports offset 30, computes a delta of 0.01, and includes the causing input record.

---

### Step D4 — Define the report structure **[MUST]**

**Objective.** A stable, serialisable output contract that the CLI, the classifier, and later the repair loop all consume.

**Owner:** Dev C · **Duration:** 20 min

**Procedure.** Define a report containing: unit identifier, total records compared, divergent count, exit-code match boolean, and the list of divergence records. Add a derived verified property implementing rule 5 from Step D1. Provide JSON serialisation.

**Acceptance test.** A report round-trips to JSON and back without loss.

---

### Step D5 — Validate against the known answer **[MUST]**

**Objective.** Prove the runner measures reality.

**Owner:** Dev C · **Duration:** 20 min · **Prerequisites:** D3, C4

**Procedure.**
1. Run the full differential comparison: oracle versus baseline, on the full 200-record input.
2. Compare the reported divergence count against the Step C4 prediction.

**Acceptance test.** The runner independently reports **113 divergences**.

**Common failures.**
- *Reported count is higher than 113* — likely an output formatting difference affecting every line, such as a padding mismatch. This is a real defect, but investigate whether it is one defect repeated 200 times or genuinely distinct.
- *Reported count is lower* — the comparison is normalising something it should not. Re-read the Step D1 rules.
- *Count is exactly 200 or 201* — every line differs, which usually means a header, encoding, or line-ending problem rather than an arithmetic one.

---

### Step D6 — Self-comparison sanity check **[MUST]**

**Objective.** Prove the runner produces no false positives. A tool that reports divergences when there are none is worse than no tool.

**Owner:** Dev C · **Duration:** 10 min

**Procedure.** Compare the golden output against itself.

**Acceptance test.** Zero divergences, verified property true. **If this fails, every other number you have is meaningless.**

---

## Phase E — Classification (Aug 8 midday, 1.5 hours)

### Step E1 — Understand why classification is deterministic **[MUST]**

**Objective.** Establish the design principle before implementing.

**Owner:** Dev B · **Duration:** 10 min

**Reasoning.** Classification could be done by a language model. It must not be. The signals — a numeric delta smaller than one unit in the last place, a ratio that is a power of ten, equal magnitude with opposite sign, equality after whitespace stripping — are unambiguous and computable. Using a model here would introduce nondeterminism into the one part of the system that must be reliable, and would weaken the claim that correctness belongs to the harness rather than the model.

This principle carries directly into the repair loop: three of the defect classes are repaired deterministically, with no inference at all.

---

### Step E2 — Implement the classification rules **[MUST]**

**Objective.** Turn each divergence into an actionable defect class.

**Owner:** Dev B · **Duration:** 50 min · **Prerequisites:** D4

**The rules, evaluated in this order.** Order matters: a scale error also satisfies some truncation conditions, so the more specific test must run first.

| Order | Class | Test | Repair strategy it implies |
|---|---|---|---|
| 1 | `PADDING` | Values are equal after stripping whitespace but unequal raw | Re-emit through the COBOL edit mask |
| 2 | `SIGN` | Absolute values equal, signs opposite | Correct the trailing-separate sign decode |
| 3 | `SCALE` | The ratio of the two values is approximately a power of ten | Recompute implied-decimal scaling from the `V` position |
| 4 | `TRUNCATION` | Both numeric, absolute delta less than one unit in the last place at the field's scale | Apply exact decimal arithmetic with round-toward-zero |
| 5 | `CONTROL_FLOW` | Record counts differ, or a field is entirely absent | Regenerate with an explicit condition table |
| 6 | `UNKNOWN` | Nothing above matched | Escalate to a human |

Attach a confidence value to each classification, derived from how cleanly the test matched. Attach the evidence — the actual values compared — so the classification is auditable rather than opaque.

**Acceptance test.** Run against the 113 real divergences. Expect approximately 87 classified `TRUNCATION` and 26 classified `CONTROL_FLOW` or `UNKNOWN` (the dormant-account defects manifest as a wrong non-zero value where zero was expected, which may fall into either bucket depending on your threshold tuning). **`UNKNOWN` should be under 15% of the total.**

**Common failures.**
- *Everything classifies as `UNKNOWN`* — your numeric parsing is failing on the edit-mask formatting. The report fields contain leading spaces and may contain a leading minus; strip and parse carefully.
- *Everything classifies as `TRUNCATION`* — your unit-in-last-place threshold is too loose. It should be strictly less than 0.01 at two-decimal scale.

---

### Step E3 — Produce the classification summary **[MUST]**

**Objective.** The single table that goes on the results slide.

**Owner:** Dev B · **Duration:** 20 min

**Procedure.** Aggregate divergences by class, producing counts and percentages, and a representative example for each class. Emit as both a printable table and JSON.

**Acceptance test.** The summary totals equal the divergence count. A discrepancy means divergences are being dropped or double-counted.

---

## Phase F — Command-Line Interface (Aug 8 afternoon, 1 hour)

### Step F1 — Define the command surface **[MUST]**

**Objective.** One command a judge can run. Not a framework.

**Owner:** Dev A · **Duration:** 10 min

**Scope for the MVP:** a single `verify` command taking the COBOL source, the Java source, and the data file, with an optional output path for the JSON report. Nothing else. Resist adding subcommands you will not demonstrate.

---

### Step F2 — Implement the command **[MUST]**

**Owner:** Dev A · **Duration:** 35 min · **Prerequisites:** D5, E3

**Procedure.**
1. Parse arguments.
2. Compile the oracle if the binary is absent or older than the source.
3. Compile the candidate.
4. Execute the differential comparison.
5. Classify the divergences.
6. Render a summary table to the terminal using `rich`: total records, divergent count, equivalence rate, and the per-class breakdown.
7. Print the first three divergences in full as illustrative examples.
8. Write the complete JSON report to disk.
9. Exit with status 0 if verified, 1 if divergences were found. This makes the tool usable in a pipeline and signals that you thought about integration.

**Acceptance test.** A single command produces a readable table, writes valid JSON, and exits 1.

---

### Step F3 — Capture demonstration screenshots **[MUST]**

**Objective.** The deck's evidence. This is why the MVP exists.

**Owner:** Dev D · **Duration:** 15 min · **Prerequisites:** F2

**Capture four images.**
1. The compiler invocation producing the oracle binary, with the shell prompt visible.
2. The oracle running and the first few lines of golden output.
3. The verify command's summary table showing 113 divergences.
4. A single divergence record from the JSON, showing field name, oracle value, candidate value, delta, and causing input.

**Guidance.** Use a large terminal font — these will be projected. Do not crop out the shell prompt; visible prompts read as authentic, cropped output reads as mocked up.

**Acceptance test.** Four PNGs exist, legible at projector resolution.

---

## Phase G — Repository and Documentation (Aug 8 afternoon, 1.5 hours)

### Step G1 — Structure the repository **[MUST]**

**Owner:** Dev C · **Duration:** 20 min

**Procedure.** Organise into: `fixtures` (COBOL source, copybooks, generated data, golden output), `baseline` (the naive Java candidate), `weaver` (the harness modules), `docs` (screenshots and specifications), and repository-root documentation. Git-ignore the build directory, compiled classes, virtual environments, and Python caches.

**Acceptance test.** A fresh clone contains no build artefacts and no compiled binaries.

---

### Step G2 — Write the README **[MUST]**

**Objective.** This is what a judge actually reads. Assume thirty seconds of attention.

**Owner:** Dev C · **Duration:** 40 min

**Required structure, in this order.**
1. **One-sentence thesis.** The compiled legacy binary is the specification; we verify translations against it automatically.
2. **The results table** — records compared, divergences found, breakdown by cause, false positives, human review required. Numbers only, no prose.
3. **Reproduction commands** — the exact sequence from clean clone to the 113 result.
4. **Architecture diagram** — the perceive/plan/act/verify/repair loop, with the MVP's implemented portion clearly marked.
5. **"Not yet implemented"** — repair loop, failure memory, local model synthesis, escalation, sandboxing. Name them explicitly.

**On point 5.** Stating what does not exist is not weakness. Every judge has seen teams imply completeness and then fail a question. Explicit scope boundaries read as engineering maturity and, practically, they inoculate you against the question you cannot answer.

**Acceptance test.** A developer who has never seen the project can follow the README from clone to the 113 result without asking questions.

---

### Step G3 — Include the specifications **[MUST]**

**Owner:** Dev C · **Duration:** 10 min

Commit the MVP SRS and this runbook into the docs directory. Few hackathon submissions include a specification; it distinguishes yours as engineering rather than a weekend hack.

---

### Step G4 — Make the repository public and test the link **[MUST]**

**Owner:** Dev C · **Duration:** 10 min

**Procedure.** Make it public, then open the link in a private browsing window with no session cookie. A repository that is private at submission time is functionally a repository that does not exist.

**Acceptance test.** The link loads for a logged-out visitor.

---

## Phase H — Deck (Aug 8 afternoon, 3 hours, parallel with Phase G)

### Step H1 — Build the argument before building slides **[MUST]**

**Owner:** Dev D · **Duration:** 30 min

**The argument, in order.** Each step must follow necessarily from the previous one:
1. Legacy migration fails at *verification*, not translation. Business logic is undocumented, so nobody can prove a translation is correct.
2. Language models are weak at COBOL. Published benchmark results show frontier models solving roughly 10% of COBOL tasks against roughly 67% on equivalent Python tasks.
3. Therefore translation output cannot be trusted, and a human reviewer is the bottleneck that makes migrations take five years.
4. **But the legacy system contains its own specification** — the compiled binary is a free, perfect oracle.
5. So: run both, diff, and every mismatch becomes a defect with a concrete reproducer, obtained with no human and no written spec.
6. We measured this. 113 of 200 records diverge. All 113 detected, zero false positives.
7. Given a concrete reproducer, repair becomes a closed loop — and the loop gets cheaper as memory accumulates.
8. It runs entirely locally, which is the only deployment model a bank can accept.

**Acceptance test.** Dev D can deliver this argument aloud in ninety seconds without slides.

---

### Step H2 — Build slides against the official template **[MUST]**

**Owner:** Dev D · **Duration:** 90 min · **Prerequisites:** H1, F3

Map the Step H1 argument onto twelve slides: title and thesis; the problem; why models alone fail; the oracle insight; the ₹0.01 bug; the 113 result; architecture; repair and memory (labelled roadmap); local-only deployment and why it matters commercially; honest scope; roadmap to the finale; team.

**Constraint.** Use the organisers' template. Submissions that ignore it get marked down for the cheapest possible reason.

---

### Step H3 — Write the results slide last **[MUST]**

**Owner:** Dev D · **Duration:** 20 min · **Prerequisites:** F2

**Procedure.** Open the actual JSON report. Copy numbers from it. Do not type numbers from memory, and do not write this slide before the tool runs.

**Reasoning.** Decks written ahead of code always drift into claims the code does not support. The gap is invisible to the authors and obvious to a judge who asks one follow-up question.

**Acceptance test.** Every number on the slide can be traced to a line in the committed JSON report.

---

### Step H4 — Adversarial review **[MUST]**

**Owner:** Dev A and B · **Duration:** 40 min · **Prerequisites:** H2, H3

**Procedure.** Two developers who did not build the deck attempt to break it. For every claim, ask: what measurement supports this? Remove or soften anything unsupported.

**Prepare answers to the three questions you will certainly be asked.**
1. *Isn't this just IBM's watsonx Code Assistant for Z?* — Those tools translate and hand the validation burden to a human. We close the loop autonomously, and cost per defect falls as failure memory accumulates.
2. *Your fixture is a toy.* — Agreed, and the six constructs in it are among the most common causes of silent production defects. The mechanism does not depend on program size; the oracle scales with it.
3. *How do you know the oracle is right?* — Point to the five hand-verified calculations from Step B5.

**Acceptance test.** No unmeasured claim survives in the deck.

---

## Phase I — Submission (Aug 8 evening, 1 hour)

### Step I1 — Fresh-clone verification **[MUST]**

**Owner:** Dev B · **Duration:** 25 min

**Procedure.** On a machine or container that has never seen the project, clone the public repository and follow the README exactly as written, changing nothing.

**Acceptance test.** The 113 result reproduces. Any step requiring undocumented knowledge is a README defect — fix the README, not your local setup.

---

### Step I2 — Final checklist **[MUST]**

**Owner:** All · **Duration:** 15 min

- [ ] Oracle compiles and runs on at least two teammates' machines
- [ ] Golden output checksum matches the reference value
- [ ] Five hand-verified calculations documented
- [ ] Baseline compiles and diverges
- [ ] Self-comparison yields zero divergences
- [ ] Verify command reports 113 and exits 1
- [ ] Fresh clone reproduces the result
- [ ] Repository public, link tested logged-out
- [ ] Deck uses the official template
- [ ] Every deck number traceable to committed JSON
- [ ] Unimplemented components explicitly named
- [ ] All four team members registered on Unstop

---

### Step I3 — Submit **[MUST]**

**Owner:** Dev D · **Time: 21:00 IST. Not later.**

**Procedure.** Upload the deck. Include the repository link in the designated field. Screenshot the confirmation. Post the screenshot to the team chat.

**Reasoning for the early submission time.** Platforms under deadline load are a well-documented way to lose a hackathon you would otherwise have placed in. Three hours of buffer costs nothing and removes the only failure mode that is entirely outside your control.

---

### Step I4 — Handover to the build phase **[SHOULD]**

**Owner:** Dev A · **Duration:** 20 min

Write a short status note: what exists, what the next component is, which acceptance tests are passing. Aug 9 begins the repair loop, and starting it cold costs an hour.

---

## Critical path

```
A1 ──▶ B2 ──▶ B4 ──▶ B5 ──▶ C3 ──▶ C4 ──▶ D2 ──▶ D3 ──▶ D5 ──▶ F2 ──▶ H3 ──▶ I3
       │                            │              │
      B1                           A2             D6
      B3                                          E2
```

Every step on the top row is blocking. **B4 and D5 are the two hard gates**: if the golden output is not deterministic, stop and fix it; if the runner does not independently report 113, stop and fix it.

## Time budget

| Phase | Hours | Cumulative |
|---|---|---|
| A — Environment | 0.75 | 0.75 |
| B — Oracle | 2.0 | 2.75 |
| C — Baseline | 1.5 | 4.25 |
| D — Runner | 2.5 | 6.75 |
| E — Classification | 1.5 | 8.25 |
| F — CLI | 1.0 | 9.25 |
| G — Repo & docs | 1.5 | 10.75 |
| H — Deck | 3.0 | 13.75 |
| I — Submission | 1.0 | 14.75 |

Roughly 15 person-hours of work. Across four people with parallelism, this is comfortably achievable in the window — **provided nobody starts building the repair loop early.**

## Cut order under time pressure

Cut from the top when you fall behind:

1. **Step A4** — Docker fallback, if everyone's native install works
2. **Step E3** — classification summary table; the raw count suffices
3. **Step E2** — classification entirely; report divergences unclassified
4. **Step F2** — the `rich` table; print raw JSON instead
5. **Step G3** — specification documents in the repo

**Never cut:** B4, B5, C3, D5, D6, H3, I1, I3. Those eight steps are the submission.
