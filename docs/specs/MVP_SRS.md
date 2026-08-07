# Software Requirements Specification
## LegacyWeaver MVP — Differential Verification Harness for COBOL-to-Java Migration

| Field | Value |
|---|---|
| Document version | 1.0 |
| Date | 07 August 2026 |
| Scope | Minimum Viable Product for PRISM Hackathon idea submission |
| Submission deadline | 08 August 2026, 23:59 IST |
| Institution | Chennai Institute of Technology |
| Standard | Adapted from IEEE Std 830-1998 |
| Supersedes | None. Subordinate to the full LegacyWeaver SRS v1.0. |

---

# 1. Introduction

## 1.1 Purpose

This document specifies the requirements for the **LegacyWeaver MVP**: a differential verification harness that determines, automatically and without human review, whether a Java translation of a COBOL program is semantically equivalent to the original.

The MVP implements the *verification* half of the LegacyWeaver architecture. The *repair* half — autonomous defect classification-driven patching, failure memory, and local model synthesis — is specified in the full SRS and is explicitly out of scope here (§2.5).

Intended audience: the development team, the PRISM evaluation panel, and reviewers assessing the submission's technical claims.

## 1.2 Scope of the MVP

### 1.2.1 What the MVP is

A command-line tool that accepts a COBOL program, a candidate Java translation, and an input data file; executes both programs against byte-identical input; compares their outputs byte-for-byte; and reports every divergence resolved to a named field with the input record that caused it.

### 1.2.2 What the MVP proves

The MVP exists to convert three assertions into measurements:

| Assertion | Measurement that establishes it |
|---|---|
| The compiled legacy binary is a usable specification | The oracle produces byte-identical output across repeated runs |
| Unconstrained translation is silently wrong | A measured divergence count against an unconstrained baseline |
| Divergence is automatically detectable without a human or a written spec | Every divergence detected and localised, with zero false positives |

### 1.2.3 What the MVP is not

The MVP does not translate COBOL, does not repair Java, does not invoke any language model, and does not claim to migrate production systems. These limitations are stated in the deliverable documentation (FR-13) rather than concealed.

## 1.3 Definitions and Abbreviations

| Term | Definition |
|---|---|
| **Oracle** | The compiled original COBOL program, treated as the authoritative specification |
| **Candidate** | A Java program purporting to be semantically equivalent to the oracle |
| **Baseline candidate** | A deliberately unconstrained translation serving as the control arm of the measurement |
| **Divergence** | Any observable difference between oracle and candidate output under the comparison contract (§3.3) |
| **Golden output** | The oracle's output for a fixed input, committed as ground truth |
| **Copybook** | A reusable COBOL data-layout definition included via `COPY` |
| **PIC clause** | COBOL type declaration specifying digits, characters, sign and implied decimal position |
| **Implied decimal (`V`)** | A decimal point that is logically present but occupies no byte |
| **REDEFINES** | A declaration that a field occupies the same bytes as a previously declared field |
| **88-level** | A named condition attached to a field, encoding a business rule |
| **Trailing separate sign** | A sign representation occupying one additional byte after the digits |
| **ULP** | Unit in the last place, at a field's declared decimal scale |
| **Trap** | A COBOL construct deliberately included in the fixture because unconstrained translation reliably mishandles it |

## 1.4 References

| ID | Reference |
|---|---|
| R1 | GnuCOBOL 3.1.2 — COBOL compiler used as the oracle runtime |
| R2 | OpenJDK 17+ — candidate runtime |
| R3 | COBOLEval (Bloop AI, 2024) — establishes poor LLM performance on COBOL, motivating §1.2.2 |
| R4 | LegacyWeaver SRS v1.0 — the full specification this document is scoped from |
| R5 | LegacyWeaver MVP Implementation Runbook v1.0 — the execution plan for these requirements |
| R6 | IEEE Std 830-1998 |

---

# 2. Overall Description

## 2.1 Product Perspective

The MVP is a self-contained command-line application with no network dependency, no service component, and no external account requirement. It reads source and data from the local filesystem and writes a report.

```
   COBOL source ─────┐
   Copybooks    ─────┤
   Input data   ─────┼──▶  ┌──────────────────────────┐
   Java candidate ───┘     │   LegacyWeaver Verify    │
                           │                          │
                           │  compile oracle          │
                           │  compile candidate       │
                           │  execute both            │──▶ Divergence report (JSON)
                           │  compare byte-for-byte   │──▶ Summary table (terminal)
                           │  resolve to fields       │──▶ Exit status
                           │  classify defects        │
                           └──────────────────────────┘
```

Within the full architecture, the MVP occupies the **Verify** stage. Perception, planning, synthesis, repair, and memory are specified in [R4] and scheduled after this submission.

## 2.2 Product Functions

| ID | Function |
|---|---|
| PF-1 | Compile a COBOL program to an executable oracle |
| PF-2 | Generate deterministic fixed-width test input |
| PF-3 | Execute the oracle and capture all output artefacts |
| PF-4 | Compile and execute a Java candidate against byte-identical input |
| PF-5 | Compare outputs byte-for-byte under a strict contract |
| PF-6 | Resolve each divergence to a named field and its causing input record |
| PF-7 | Classify divergences into defect classes deterministically |
| PF-8 | Report results as a terminal summary, a JSON artefact, and an exit status |

## 2.3 User Classes

| Class | Characteristics | Requirements they drive |
|---|---|---|
| **Evaluator** (PRISM panel) | Assesses technical claims in limited time; may reproduce results | FR-11, FR-12, FR-13 |
| **Migration engineer** (target user) | Java developer, limited COBOL knowledge | FR-7, FR-8, FR-10 |
| **Developer** (team) | Extends the MVP into the full system after Aug 8 | FR-6, NFR-6, NFR-7 |

## 2.4 Operating Environment

| Component | Requirement |
|---|---|
| Operating system | Linux (Ubuntu 22.04+), macOS, or Windows via WSL2 |
| COBOL compiler | GnuCOBOL 3.x. **Version 2.x is not supported** — its default arithmetic behaviour differs and silently invalidates the golden output |
| Java | JDK 17 or later. A JRE is insufficient; `javac` is required |
| Python | 3.11 or later |
| Memory | 2 GB |
| Disk | 500 MB |
| Network | **None at any point.** Required only for initial toolchain installation |

## 2.5 Explicit Exclusions

The following are specified in [R4] and are **not** requirements of this document. Their absence is a deliberate scope decision, not an omission.

| Excluded | Rationale |
|---|---|
| COBOL parsing, paragraph segmentation, dependency planning | Belongs to the Perceive and Plan stages; not needed to prove the verification thesis |
| Java code synthesis | The MVP consumes a candidate; it does not produce one |
| Language model invocation of any kind | The MVP is fully deterministic |
| Repair loop, failure memory, escalation | The verification mechanism must be proven before repair built on it has meaning |
| Container sandboxing | Deferred; the MVP executes trusted, hand-written code only |
| CICS, DB2, IMS, VSAM, JCL, inter-program `CALL` | Out of scope for the entire project, not merely the MVP |

## 2.6 Assumptions and Dependencies

| ID | Assumption |
|---|---|
| A1 | The fixture COBOL program compiles under GnuCOBOL 3.x without modification |
| A2 | Both programs are deterministic: identical input yields identical output. No dependence on wall-clock time, randomness, or external state |
| A3 | Both programs read the same input file format and write the same output file format |
| A4 | Test input can be synthesised from the field layout; no production data is required |
| A5 | The evaluating machine can run both toolchains natively or in a container |

## 2.7 Design Constraints

| ID | Constraint |
|---|---|
| DC-1 | **No network egress at runtime.** No API, no key, no account |
| DC-2 | All dependencies MIT, Apache-2.0, or GPL-compatible |
| DC-3 | Fixed-point arithmetic in the harness must use exact decimal representation, never binary floating point. The harness must not introduce comparison error of its own |
| DC-4 | Correctness is determined **solely** by byte comparison. No tolerance, threshold, heuristic, or model may participate |
| DC-5 | Every result presented externally must be reproducible from a clean checkout |
| DC-6 | Delivery by 08 August 2026 constrains implementation to requirements marked **[MUST]** |

---

# 3. Specific Requirements

Priority: **[MUST]** blocks submission · **[SHOULD]** improves submission, first to be cut.

## 3.1 Fixture Requirements

### FR-1 — Oracle program **[MUST]**
The system shall include a COBOL batch program that compiles under GnuCOBOL 3.x without modification and represents a realistic financial computation over fixed-width sequential records.

*Verification:* compilation succeeds; the produced binary executes to a zero exit status.

### FR-2 — Planted constructs **[MUST]**
The fixture shall contain no fewer than six COBOL constructs that unconstrained translation reliably mishandles. Each shall be documented in the source with an identifier and its failure mode.

Required constructs:

| ID | Construct | Failure mode under naive translation |
|---|---|---|
| T1 | Arithmetic without explicit rounding | COBOL truncates toward zero by default; Java conventionally rounds. Sub-unit error per record, compounding in totals |
| T2 | Implied decimal position | Storage contains no decimal point; misreading yields a 100× magnitude error |
| T3 | `REDEFINES` overlay on a flag group | The overlay is invisible without parsing the data division; conditional logic silently fails |
| T4 | 88-level condition driving a tiered rate | Condition semantics inlined incorrectly; wrong branch selected |
| T5 | Numeric edit mask with fixed width | Java's general numeric formatting produces different column alignment |
| T6 | Trailing separate sign | The sign character is unfamiliar outside COBOL and is parsed as a digit or ignored |

*Verification:* each construct is present in the source and annotated.

### FR-3 — Structural divergence guarantee **[MUST]**
The planted constructs shall cause divergence **by language semantics rather than by chance**, such that the divergence is reproducible on any conforming toolchain and does not depend on a translator happening to make a mistake.

*Verification:* divergence is observed on every run across every developer machine.

### FR-4 — Deterministic input generation **[MUST]**
The system shall generate the input file from a fixed seed. Two invocations shall produce byte-identical files.

The generated set shall contain no fewer than 200 records and shall include, for each planted construct, records that exercise it — including arithmetic values engineered to fall immediately above a truncation boundary.

*Verification:* two generated files compare equal; record count and fixed width confirmed.

### FR-5 — Golden output **[MUST]**
The oracle's output for the generated input shall be committed to the repository as ground truth, together with its cryptographic checksum.

*Verification:* ten consecutive executions produce identical checksums.

### FR-6 — Independent validation of the oracle **[MUST]**
No fewer than five output records, selected to span the distinct logic paths of the program, shall be verified by manual calculation against the field layout and the program's stated semantics. The calculations shall be recorded in the repository.

*Rationale:* machine self-agreement establishes determinism, not correctness. Without independent validation, the entire measurement could be internally consistent and externally wrong.

*Verification:* five documented calculations match the golden output.

## 3.2 Baseline Candidate Requirements

### FR-7 — Baseline translation **[MUST]**
The system shall include a Java program that reads the same input, performs the same nominal computation, and writes the same nominal output format, implemented **without** the constraints that COBOL semantics require.

Each deviation shall be one that unconstrained translation plausibly produces — specifically: binary floating-point arithmetic for monetary values; round-half-up rather than truncation; comparison of a flag group as a whole string rather than through its `REDEFINES` overlay; and general-purpose numeric formatting rather than the declared edit mask.

### FR-8 — Declared control arm **[MUST]**
The baseline source shall state, in a header comment, that it is a deliberately unconstrained translation serving as the control arm of a measurement, and shall enumerate its introduced deviations.

*Rationale:* an undeclared strawman invalidates the measurement and, if discovered, damages the submission's credibility more than a lower divergence count would. A declared control arm is standard experimental practice.

*Verification:* the header comment is present and enumerates every deviation.

## 3.3 Comparison Requirements

### FR-9 — Dual execution **[MUST]**
The system shall execute oracle and candidate against byte-identical input in isolated working directories such that neither can observe or overwrite the other's artefacts. The input file shall be **copied**, not regenerated, for each.

Each execution shall be subject to a wall-clock timeout of no more than 30 seconds. The system shall capture standard output, standard error, exit status, and all produced output files. Absence of an expected output file shall be recorded as a divergence, not treated as a harness error.

### FR-10 — Comparison contract **[MUST]**
Output comparison shall observe the following rules without exception:

1. Comparison is byte-for-byte.
2. The only permitted normalisation is line-ending conversion.
3. Trailing whitespace differences constitute genuine divergences and shall not be normalised.
4. Exit statuses shall be compared.
5. A candidate is *verified* if and only if divergence count is zero **and** exit statuses match.
6. No tolerance, threshold, heuristic, or language model shall participate in this determination.

*Rationale for rule 3:* fixed-width reports are consumed by downstream systems that parse by column position. A width difference is a defect regardless of visual similarity.

*Rationale for rule 6:* the value of the oracle derives entirely from its being unarguable. Any relaxation forfeits the project's central claim.

### FR-11 — Field resolution **[MUST]**
Each divergence shall be resolved against a declared output layout and reported with: record index; byte offset; field identifier; oracle value; candidate value; numeric delta where both values parse as numbers; and **the input record that produced the divergent output**.

*Rationale:* the input record is what makes the divergence a reproducer rather than an observation, and it is the precondition for automated repair in the subsequent phase.

*Verification:* given a candidate differing in exactly one known field, the system reports exactly one divergence with the correct field identifier, offset, delta, and causing input record.

### FR-12 — No false positives **[MUST]**
Comparison of the golden output against itself shall report zero divergences and a verified status.

*Rationale:* a verification tool that reports spurious divergences is worse than no tool, because every subsequent number it produces is uninterpretable.

## 3.4 Classification Requirements

### FR-13 — Deterministic classification **[SHOULD]**
Divergences shall be classified by rules evaluated in a fixed order, the more specific tests preceding the more general:

| Order | Class | Test |
|---|---|---|
| 1 | `PADDING` | Values equal after whitespace removal, unequal raw |
| 2 | `SIGN` | Magnitudes equal, signs opposite |
| 3 | `SCALE` | Ratio of values approximates a power of ten |
| 4 | `TRUNCATION` | Both numeric; absolute delta strictly less than one ULP at field scale |
| 5 | `CONTROL_FLOW` | Record counts differ, or a field is absent |
| 6 | `UNKNOWN` | No preceding test matched |

Classification shall use exact decimal arithmetic (DC-3) and shall not invoke a language model.

*Rationale:* these signals are unambiguous and computable. Delegating them to a model would introduce nondeterminism into the most reliability-critical component and would weaken the claim that correctness resides in the harness.

*Verification:* against the measured divergence set, `UNKNOWN` shall not exceed 15% of classifications.

### FR-14 — Classification summary **[SHOULD]**
The system shall aggregate divergences by class with counts, percentages, and one representative example per class. Summary totals shall equal the divergence count.

## 3.5 Interface Requirements

### FR-15 — Command-line interface **[MUST]**
The system shall expose a single verification command accepting: the COBOL source path, the Java candidate path, the input data path, and an optional report output path.

The command shall compile both programs as required, execute the comparison, classify results where FR-13 is implemented, render a terminal summary, write a JSON report, and exit with status 0 when verified and non-zero otherwise.

### FR-16 — Terminal output **[MUST]**
The summary shall present: total records compared; divergence count; equivalence rate; per-class breakdown where available; and no fewer than three fully expanded divergence examples.

### FR-17 — Machine-readable report **[MUST]**
The system shall write a JSON report containing the complete comparison result. The stored divergence list may be capped at 50 entries provided the total count remains accurate and the cap is indicated.

## 3.6 Documentation Requirements

### FR-18 — Reproduction instructions **[MUST]**
The repository shall document a command sequence reproducing the reported divergence count from a clean checkout on a supported platform, assuming only the toolchain of §2.4.

*Verification:* a developer with no prior exposure to the project reproduces the result following the documentation without recourse to the team.

### FR-19 — Results disclosure **[MUST]**
The repository shall state, in tabular form: records compared, divergences found, breakdown by cause, false-positive count, and human review required.

### FR-20 — Scope disclosure **[MUST]**
The repository and the submitted presentation shall each contain an explicit enumeration of components specified in [R4] but not implemented in the MVP.

*Rationale:* the MVP implements one stage of a larger architecture. Presenting it without stating that boundary would misrepresent the submission, and the boundary is discoverable by any reviewer who reads the code.

---

# 4. Non-Functional Requirements

## 4.1 Performance

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Complete verification cycle over 200 records, including both compilations | ≤ 30 s |
| NFR-2 | Comparison and classification, excluding compilation | ≤ 5 s |
| NFR-3 | Clean checkout to first result, excluding toolchain installation | ≤ 10 min |

## 4.2 Reliability and Determinism

| ID | Requirement |
|---|---|
| NFR-4 | Two executions with identical inputs shall produce identical reports |
| NFR-5 | Neither program's failure shall crash the harness; abnormal termination shall be reported as a divergence |
| NFR-6 | No execution shall be unbounded; timeouts apply to both programs |

## 4.3 Portability

| ID | Requirement |
|---|---|
| NFR-7 | The system shall operate on any platform of §2.4 with no configuration beyond toolchain installation |
| NFR-8 | The system shall depend on no service requiring an account, credential, or payment |
| NFR-9 | A container definition shall be available as a fallback for platforms where native installation fails **[SHOULD]** |

## 4.4 Security and Isolation

| ID | Requirement |
|---|---|
| NFR-10 | The system shall make no network connection during a verification run |
| NFR-11 | Executions shall occur in isolated working directories under a wall-clock bound |
| NFR-12 | Input data shall not be logged verbatim beyond the specific records required for divergence diagnosis |

## 4.5 Maintainability

| ID | Requirement |
|---|---|
| NFR-13 | Execution, comparison, classification, and presentation shall be separable modules with no circular dependency |
| NFR-14 | The output layout shall be declared as data, not embedded in comparison logic, so that a second fixture requires no code change |
| NFR-15 | The defect taxonomy shall be extensible without modification to the comparison module |

*Rationale for NFR-13 through NFR-15:* the repair loop, failure memory, and synthesis stages of [R4] attach to these interfaces between 9 and 12 August. Coupling introduced now is paid for in that window.

---

# 5. Data Requirements

## 5.1 Input record layout

The system shall interpret input records according to a declared field table specifying, for each field: name, level, PIC clause, byte offset, byte width, decimal scale, sign presence and encoding, and any `REDEFINES` relationship.

Offsets shall be derived under these rules:
- A character field occupies exactly its declared character count.
- A numeric field occupies one byte per declared digit position. **The implied decimal marker occupies zero bytes.**
- A trailing separate sign occupies one additional byte.
- A `REDEFINES` field begins at its target's offset and does not extend the record.

## 5.2 Output record layout

The system shall interpret oracle and candidate output according to a declared field table giving name, start offset, width, and whether the field is numeric. This table is distinct from §5.1 and shall be derived from the report line declaration in the COBOL source.

## 5.3 Divergence record

Each divergence shall carry: record index, byte offset, field identifier, oracle value, candidate value, numeric delta or null, and causing input record.

## 5.4 Report record

Each report shall carry: unit identifier, total records compared, divergent count, exit-status match, derived verified status, and the divergence list.

---

# 6. Acceptance Criteria

Every criterion below shall be demonstrated before submission.

## 6.1 Functional acceptance

| ID | Criterion | Requirement | Method |
|---|---|---|---|
| AC-1 | Oracle compiles and executes | FR-1 | Compilation and execution succeed |
| AC-2 | Golden output is deterministic | FR-5 | Ten runs, identical checksum |
| AC-3 | Oracle independently validated | FR-6 | Five documented manual calculations match |
| AC-4 | Input generation is deterministic | FR-4 | Two files compare equal |
| AC-5 | Baseline diverges | FR-7 | Output differs from golden |
| AC-6 | Baseline declares its deviations | FR-8 | Header comment present and complete |
| AC-7 | Divergences detected | FR-9, FR-10 | Reported count matches independently predicted count |
| AC-8 | Divergences localised | FR-11 | Single-field test yields correct field, offset, delta, input |
| AC-9 | **No false positives** | FR-12 | Self-comparison yields zero divergences |
| AC-10 | Classification bounded | FR-13 | `UNKNOWN` ≤ 15% |
| AC-11 | Single-command operation | FR-15 | One invocation produces summary, JSON, and exit status |

## 6.2 Non-functional acceptance

| ID | Criterion | Requirement | Method |
|---|---|---|---|
| AC-12 | Reproducible from clean checkout | FR-18, DC-5 | Independent developer reproduces the result |
| AC-13 | Operates offline | DC-1, NFR-10 | Full run with network egress blocked |
| AC-14 | No credentialed dependency | NFR-8 | Fresh-machine installation succeeds |
| AC-15 | Within performance budget | NFR-1 | Timed execution |
| AC-16 | Scope disclosed | FR-20 | Unimplemented components enumerated in repository and deck |

## 6.3 Blocking criteria

**AC-2, AC-3, AC-9 and AC-12 are blocking.** Their failure invalidates every reported result:

- AC-2 failure means the ground truth is not stable.
- AC-3 failure means the ground truth may be wrong.
- AC-9 failure means reported divergences may not be real.
- AC-12 failure means the results cannot be independently confirmed and are, for evaluation purposes, assertions.

---

# 7. Traceability

## 7.1 Requirements to PRISM Theme 1 evaluation criteria

| Criterion | Weight | Requirements |
|---|---|---|
| Innovation & Originality | 20% | FR-9, FR-10, FR-11 — the oracle-based verification mechanism |
| Agentic Intelligence | 25% | FR-11, FR-13 — divergence localisation and deterministic diagnosis; the precondition for the autonomous repair loop of [R4] |
| Technical Implementation | 20% | FR-1 through FR-6, FR-12, NFR-4, NFR-13 through NFR-15 |
| Real-World Impact & Feasibility | 15% | DC-1, NFR-7, NFR-8 — commodity hardware, offline operation |
| User Experience & Demonstration | 10% | FR-15, FR-16, FR-17, FR-18 |
| Presentation & Communication | 10% | FR-19, FR-20 — measured rather than asserted results; disclosed scope |

## 7.2 MVP requirements to full-system requirements

| MVP requirement | Full SRS [R4] counterpart | Relationship |
|---|---|---|
| FR-9 | FR-4.2, FR-4.3 | MVP omits container sandboxing |
| FR-10 | FR-4.4 | Identical contract |
| FR-11 | FR-4.4 | Identical |
| FR-12 | FR-4.5 | Identical |
| FR-13 | FR-5.1 | MVP implements 6 of 7 classes; `SYNTHESIS_FAILURE` is not applicable |
| FR-7 | FR-8.3 | The MVP baseline becomes the full system's baseline comparison mode |
| — | FR-1.x, FR-2.x, FR-3.x, FR-5.2–5.5, FR-6.x, FR-7.x | Not implemented in MVP |

---

# 8. Open Issues

| ID | Issue | Resolution required by |
|---|---|---|
| OI-1 | Whether dormant-account defects classify as `CONTROL_FLOW` or `UNKNOWN` depends on ULP threshold tuning; the boundary is not yet fixed | Step E2 of [R5] |
| OI-2 | The candidate execution path is untested against a real JDK at the time of writing | Step C3 of [R5] |
| OI-3 | Behaviour under GnuCOBOL 2.x is unspecified and expected to differ; currently handled by prohibition rather than detection | Post-submission |
| OI-4 | The output layout table is derived manually from the COBOL source; automatic derivation is deferred to the Perceive stage of [R4] | Post-submission |

---

**End of document.**
