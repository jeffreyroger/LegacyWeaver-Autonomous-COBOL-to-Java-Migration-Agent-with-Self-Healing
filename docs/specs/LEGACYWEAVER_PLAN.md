# LegacyWeaver — Implementation Plan

**PRISM Hackathon · Theme 1 · CIT**
Submission: 8 Aug 26, 23:59 IST · Finale: 12 Aug 26, 08:00–18:00 IST

---

## 0. Scope Contract

Read this before every commit. If a task isn't on the IN list, it doesn't get built before Aug 12.

### IN
- **One** COBOL batch program (`INTCALC`, ~250 lines) + one copybook + one flat input file
- **One** stretch program (`FEECALC`) sharing a bug class with INTCALC — used only to demo memory reuse
- GnuCOBOL execution of the original in Docker
- Paragraph-level Java generation (one COBOL paragraph → one Java method)
- Differential test runner: same inputs → both binaries → byte-diff
- Repair loop with a fixed defect taxonomy (5 classes)
- Failure memory with vector retrieval
- Escalation card after K=3 failed repairs
- Terminal UI (mandatory) + web trace UI (only if M4 lands on time)

### OUT — say "roadmap" on stage, do not build
- CICS, DB2, IMS, VSAM
- Multi-program call graphs / `CALL` statements
- JCL parsing (mention it; the JCL is a prop for one slide)
- Spring Boot, REST controllers, microservice decomposition
- Anything touching a real mainframe
- Anonymised production data (we generate our own)

### The line to say out loud
> "We demonstrate the verification-and-repair mechanism on a batch program with realistic numeric and layout constructs. Extending to CICS and DB2 is engineering, not invention — the oracle is unchanged."

---

## 1. The Non-Negotiable Design Decisions

Four choices determine whether this works. Do not relitigate them mid-week.

**1. Paragraph granularity.** The LLM never sees more than one COBOL paragraph at a time. Whole-program translation produces Java that doesn't compile, and then the repair loop burns its budget on syntax errors instead of semantics — which is off-thesis and boring to watch.

**2. The oracle is the running binary.** Never an LLM judging correctness. Never a human. `diff` on captured stdout + output files, exit code, and nothing else. This is the entire intellectual claim of the project; keep it uncontaminated.

**3. Defects are made structural, not hoped for.** COBOL `COMPUTE` truncates unless you write `ROUNDED`. Generated Java will use standard arithmetic. The divergence is guaranteed by the language semantics, not by luck. Same for fixed-width padding and signed-field handling. The demo bug appears on every run, on any machine.

**4. Cut ProLeap if it isn't running by end of Aug 9.** It is the most impressive-sounding component and the least load-bearing one. Regex over column-8 labels splits paragraphs in 20 minutes. The demo is cookies being tasted, not parse trees.

---

## 2. Repo Layout

```
legacyweaver/
├── fixtures/
│   ├── cobol/
│   │   ├── INTCALC.cbl          # primary demo program
│   │   ├── FEECALC.cbl          # memory-reuse demo
│   │   └── copybooks/ACCTREC.cpy
│   ├── data/
│   │   ├── accounts.dat         # 200 handcrafted records
│   │   └── edge_cases.dat       # boundary/adversarial
│   └── expected/                # golden outputs from GnuCOBOL
├── docker/
│   ├── cobol.Dockerfile         # gnucobol
│   └── java.Dockerfile          # eclipse-temurin:21-jdk
├── weaver/
│   ├── perceive/
│   │   ├── splitter.py          # COBOL → paragraphs
│   │   ├── copybook.py          # PIC clause → FieldSpec
│   │   └── dataflow.py          # var read/write per paragraph
│   ├── plan/graph.py            # dependency DAG + topo order
│   ├── act/
│   │   ├── prompts.py
│   │   └── generate.py          # paragraph → Java method
│   ├── verify/
│   │   ├── fuzzer.py            # FieldSpec → test vectors
│   │   ├── runner.py            # dual execution + diff
│   │   └── classify.py          # diff → DefectClass
│   ├── repair/
│   │   ├── strategies.py        # DefectClass → patch prompt
│   │   └── memory.py            # vector store of FailureCase
│   ├── orchestrator.py          # LangGraph state machine
│   └── cli.py
├── ui/                          # only if M4 lands
├── runs/                        # traces, metrics, cached LLM calls
└── PLAN.md
```

---

## 3. The Fixture — Build This First

`INTCALC` is the whole demo. Every trap is deliberate. Write it today.

### Copybook `ACCTREC.cpy`
```cobol
       01  ACCT-REC.
           05  AR-ID              PIC X(10).
           05  AR-BALANCE         PIC S9(9)V99.
           05  AR-RATE            PIC S9(1)V9(5).
           05  AR-TYPE            PIC X(01).
           05  AR-DATE.
               10  AR-YY          PIC 9(02).
               10  AR-MM          PIC 9(02).
               10  AR-DD          PIC 9(02).
           05  AR-FLAGS           PIC X(04).
           05  AR-FLAGS-R REDEFINES AR-FLAGS.
               10  AR-DORMANT     PIC X(01).
               10  AR-HOLD        PIC X(01).
               10  AR-RESERVED    PIC X(02).
```

### Planted traps

| # | Construct | Why LLMs get it wrong | Observable symptom |
|---|---|---|---|
| T1 | `COMPUTE` without `ROUNDED` | Java rounds or uses `double` | Off by ₹0.01–0.03 per record, compounding in the total |
| T2 | `PIC S9(9)V99` implied decimal | Read as integer, or decimal point assumed present in file | Value off by 100× |
| T3 | `REDEFINES` on `AR-FLAGS` | Treated as a separate field, not the same 4 bytes | Dormant accounts accrue interest they shouldn't |
| T4 | `88`-level `PREMIUM` with tiered rate | Condition name inlined as a string compare on the wrong field | Wrong rate branch |
| T5 | Fixed-width output via `PIC -9(9).99` | Java prints `-123.4` not `      -123.40` | Trailing/leading space mismatch |
| T6 | `PERFORM VARYING` with `AFTER` | Off-by-one on loop bounds | Last record skipped |

### Core paragraph — the money bug
```cobol
       2100-CALC-INTEREST.
           MOVE AR-TYPE TO WS-ACCT-TYPE.
           IF PREMIUM
               COMPUTE WS-APPLIED-RATE = AR-RATE * 1.15
           ELSE
               MOVE AR-RATE TO WS-APPLIED-RATE
           END-IF.
           IF AR-DORMANT = "Y"
               MOVE ZERO TO WS-INTEREST
           ELSE
               COMPUTE WS-INTEREST =
                   AR-BALANCE * WS-APPLIED-RATE / 365
           END-IF.
           ADD WS-INTEREST TO WS-TOTAL.
```

That `COMPUTE` truncates. Naive Java won't. **This is the ₹0.03 on stage.**

### Test data requirements (`accounts.dat`, 200 records)
- 60 ordinary balances (₹10k–₹5L)
- 40 balances chosen so `balance * rate / 365` lands just above a truncation boundary (e.g. `…x.xx5`) — these are the records that will diverge; verify by hand that at least 15 do
- 25 negative balances (overdrafts)
- 25 dormant flag set
- 20 premium accounts
- 15 zero balance / zero rate
- 15 max-width `999999999.99`

Generate with a small Python script so you can regenerate deterministically. Seed it.

### `FEECALC` (stretch, ~80 lines)
Same T1 truncation bug class, different arithmetic (flat fee tiers). Its only purpose: on Aug 12, migrating it costs **zero LLM calls** because memory already holds the patch. Build it last.

**Exit criteria for §3:** `cobc -x INTCALC.cbl && ./INTCALC` produces `report.out` deterministically in Docker. Golden output committed to `fixtures/expected/`.

---

## 4. Milestones

| ID | Deliverable | Owner | Due | Exit criteria |
|---|---|---|---|---|
| M0 | Fixtures + GnuCOBOL Docker | Dev A | Aug 8, 18:00 | Golden output reproducible; ≥15 records provably diverge under naive arithmetic |
| M1 | Deck submitted | Dev D | **Aug 8, 21:00** | Uploaded on Unstop with 3h buffer |
| M2 | Differential runner | Dev C | Aug 9, 22:00 | `weaver verify --java X.java` returns structured diff JSON |
| M3 | Perceive + generate + orchestrator | Dev B | Aug 10, 22:00 | Full run produces compiling Java for ≥80% of paragraphs |
| M4 | Repair loop + memory | Dev B + C | Aug 11, 18:00 | INTCALC reaches zero divergence autonomously |
| M5 | UI + metrics + rehearsal | Dev D + A | Aug 11, 23:00 | **Backup video recorded** |
| M6 | Polish, buffer | All | Aug 12, 14:00 | Feature freeze at 14:00. No exceptions. |

**Hard rule:** M2 before M3. If you build generation before verification you'll spend three days eyeballing Java, which is exactly the failure mode this project exists to critique.

---

## 5. Day-by-Day

### Aug 7 (tonight) — 3–4 hrs
- **A:** Write `INTCALC.cbl` + copybook. Get it compiling under GnuCOBOL locally (`sudo apt install gnucobol` or `docker run -v $PWD:/src ubuntu`).
- **B:** Generate `accounts.dat`. Hand-verify five interest calculations against the COBOL output with a calculator — you must know the truth independently.
- **C:** `docker/cobol.Dockerfile` + `docker/java.Dockerfile`, both building.
- **D:** Deck skeleton in the official template. Slides 1–5 drafted.

### Aug 8 — submission day
- **Morning:** finish fixtures. Take a **screenshot of the terminal** showing GnuCOBOL compiling and running your program. This goes in the deck and puts you above every slide-only submission.
- **Midday:** D builds deck slides 6–12 with the architecture diagram.
- **17:00:** push a public GitHub repo — fixtures + `README.md` with architecture diagram + this plan. One hour of work, signals you're already executing.
- **21:00:** **submit.** Do not wait for 23:00. Unstop under load at deadline is a known way to lose a hackathon.
- **Evening:** C starts `runner.py`.

### Aug 9 — the plumbing day (least glamorous, highest risk)
- **A + C:** finish the differential runner.
  - Input: path to Java file, path to test-vector set
  - Steps: `javac` in container → run both → capture stdout + `report.out` + exit code → normalise line endings → diff
  - Output: `{status, first_divergence: {record_id, field, cobol_value, java_value, byte_offset}, divergence_count}`
  - **Structured diff, not a text blob.** The repair loop's quality is bounded by how precise this JSON is.
- **B:** paragraph splitter + copybook parser.
  - `splitter.py`: paragraph labels are non-comment lines starting in area A (col 8–11) ending in `.`. Regex is fine.
  - `copybook.py`: `^\s+(\d{2})\s+([\w-]+)\s+(?:PIC|PICTURE)\s+([\dSVX9()\.]+)` → `FieldSpec(level, name, pic, offset, width, scale, signed)`. Compute byte offsets by walking levels.
- **B (evening):** attempt ProLeap. **Hard stop 23:00.** If the Maven build isn't producing an ASG dump by then, delete the branch and use the regex path. Do not carry this into Aug 10.

### Aug 10 — generation + orchestration
- **B:** `generate.py`. One paragraph + its FieldSpecs + the variables it reads/writes → one Java method. Prompt sketch:

  > You are translating a single COBOL paragraph to a Java method.
  > **Context:** field layouts (name, PIC, offset, width, scale, signed), variables read, variables written.
  > **Rules:** every numeric field is `BigDecimal` with the scale implied by its PIC V position. Output only the method body. Do not invent helper methods. Do not add comments.
  > **Output:** JSON `{ "method": "...", "assumptions": ["..."] }`

  Capture `assumptions` — it feeds the escalation card and is a great slide.

- **C:** `fuzzer.py`. FieldSpec → test vectors: min, max, zero, negative-max, boundary-just-over-truncation, all-spaces, all-nines. ~40 vectors per field is plenty; combinatorial explosion helps nobody.
- **A:** `orchestrator.py` skeleton in LangGraph. Nodes: `perceive → plan → generate → verify → (pass? commit : diagnose) → repair → verify …`. Cap iterations at K=3.
- **D:** metrics collection — every run writes `runs/<ts>/trace.jsonl` with one event per node transition. This file *is* your demo and your results slide.

### Aug 11 — repair loop, the day that matters
- **B + C:** defect classification + repair strategies (§6).
- **B:** memory (§7). Seed with 3 cases discovered during dev — legitimate, not fabricated: they're real failures your loop actually fixed.
- **A:** end-to-end runs. Target: INTCALC reaches zero divergence in ≤3 repair iterations per paragraph.
- **D:** UI. Minimum viable is a streaming terminal with coloured paragraph status. Only build the graph view if everything else is green by 18:00.
- **20:00:** **feature freeze.**
- **21:00–23:00:** record the backup video. Full 5-minute demo, screen + audio. If the venue wifi dies on Aug 12, this saves the project.
- **23:00:** cache every LLM response from the successful run into `runs/demo_cache/`. Add `--replay` to `cli.py` that serves from cache. **Never let an API timeout eat your five minutes.**

### Aug 12 — finale
- 08:00–10:00 setup, verify Docker works on venue machine/laptop, test projector resolution
- 10:00–14:00 polish, four timed rehearsals minimum
- **14:00 freeze.** Nothing after this except rehearsal.
- Bring: laptop, charger, HDMI adapter, phone hotspot, USB with backup video, printed one-pager

---

## 6. Defect Taxonomy and Repair Strategies

The repair loop is only as good as this table. Hardcode the five classes; the LLM's job is to apply a strategy, not invent one.

| Class | Detection signal | Repair strategy | Confidence |
|---|---|---|---|
| `TRUNCATION` | Numeric diff, \|Δ\| < 1 unit of last decimal place | Wrap in `.setScale(n, RoundingMode.DOWN)`; replace any `double` with `BigDecimal` | High — apply directly |
| `SCALE` | Diff is exactly 10^k × expected | Re-read PIC `V` position; fix implied decimal scaling | High |
| `SIGN` | Values equal in magnitude, opposite sign | Fix signed-field decode / sign-trailing handling | High |
| `PADDING` | `strip()`-equal but raw-unequal | Pad to PIC width, right-justify numerics, left-justify alphanumerics | High — deterministic, no LLM needed |
| `CONTROL_FLOW` | Wrong record count, or field entirely absent | Re-derive branch conditions from `88`-levels and `REDEFINES` overlap; regenerate paragraph with explicit condition table | Low — most likely to escalate |

**Repair loop rules:**
- Try memory first (§7). Cache hit → apply patch → verify. Zero LLM calls.
- Miss → classify → strategy-specific prompt including: the failing input record, both outputs, the byte offset, the current Java, and the strategy hint.
- Each attempt must produce a **different** patch. Track patch hashes; if the LLM repeats itself, escalate immediately rather than burning attempt 3.
- After K=3, escalate.

**Escalation card contents** (this is a slide and a demo beat):
```
PARAGRAPH: 2100-CALC-INTEREST
FAILING INPUT: AC00000173 | bal=  412750.00 | rate=0.06250 | type=P
COBOL:   70.66    JAVA: 70.67    Δ=0.01
CLASS:   TRUNCATION (confidence 0.91)
TRIED:
  1. setScale(2, HALF_UP)   → still diverges (+0.01)
  2. setScale(2, DOWN)      → fixed 14/15, record 173 still off
  3. BigDecimal division w/ MathContext(34) → no change
SUSPECT COBOL: line 142, COMPUTE without ROUNDED, intermediate
               precision differs from IEEE double
ASSUMPTIONS MADE: ["rate applied before division", "365-day year"]
→ HUMAN DECISION REQUIRED
```

Note the honesty: the agent says what it tried *and why each failed*. That's more impressive than a perfect run.

---

## 7. Failure Memory

Schema:
```python
FailureCase = {
  "id": str,
  "symptom_signature": str,   # "numeric_diff|delta<0.01|scale=2|op=COMPUTE_DIV"
  "defect_class": str,
  "cobol_construct": str,     # normalised source of the offending statement
  "root_cause": str,
  "patch": str,               # unified diff on the Java method
  "verified": bool,
  "hit_count": int
}
```

Retrieval: embed `symptom_signature + cobol_construct`, cosine search, threshold 0.85. On hit, apply the stored patch **without an LLM call** and verify. If verification fails, fall through to normal repair and store the new case.

**The demo beat:** INTCALC's truncation bug takes 4 LLM calls to fix. FEECALC's same-class bug takes **0** — cache hit, instant green. Show the call counter on screen. This is the most persuasive 20 seconds in your presentation because it makes memory *visible* rather than claimed.

Seed with 3 real cases from dev. Do not fabricate entries — a judge who asks "where did these come from?" deserves a true answer.

---

## 8. Metrics to Collect

Instrument from Aug 10 so you have real numbers, not estimates.

| Metric | How | Target |
|---|---|---|
| Semantic equivalence, pre-repair | divergent vectors / total, first generation | Expect 20–40% divergent — **a high number here is good for you** |
| Semantic equivalence, post-repair | same, after loop | ≥95% |
| Mean repair iterations | from trace.jsonl | ≤2.0 |
| Autonomous resolution rate | fixed without escalation | ≥80% |
| LLM calls per defect, run 1 vs run 2 | counter | ~4 → 0 on memory hit |
| Baseline delta | single-shot GPT/Claude translation, same fixture, same harness | Baseline should fail on T1, T3, T5 |

**Run the baseline comparison for real** and record it. "Naive LLM: 14 divergent records. LegacyWeaver: 0." One chart, more convincing than any architecture diagram.

---

## 9. Demo Script — 5 Minutes

| Time | Beat | Screen |
|---|---|---|
| 0:00–0:30 | "This calculates daily interest on savings accounts. 250 lines. Written in 1997. The author retired in 2004 and the spec was never written down." | INTCALC.cbl scrolling |
| 0:30–1:15 | "Here's what a frontier LLM produces. It compiles. It runs. Let's check it." Run both. **₹0.03 divergence on a ₹4.2 lakh balance.** *Pause.* "Compiles, runs, loses money. Every day. On every account. And nothing tells you." | side-by-side diff, red |
| 1:15–3:15 | Run LegacyWeaver. Paragraphs light up amber → differential runner fires → one goes red → classification appears → patch → **green**. Narrate the loop, don't read the screen. | live trace |
| 3:15–4:00 | "Second program, same bug class." Run FEECALC. Instant green. **"Zero LLM calls. It remembered."** | call counter: 0 |
| 4:00–4:40 | Trigger the unrepairable case → escalation card. "It knows what it doesn't know, and it hands the human a reproducer instead of a shrug." | escalation card |
| 4:40–5:00 | Numbers slide + the scope line from §0. | metrics chart |

**Rehearsal rules:** D narrates, A drives the keyboard. Never the same person. Four timed run-throughs minimum on Aug 12 morning. Time to 4:30, not 5:00.

---

## 10. Risk Register

| Risk | P | Impact | Mitigation |
|---|---|---|---|
| ProLeap eats two days | High | Medium | Hard cut Aug 9, 23:00. Regex path is pre-built as default. |
| Generated Java won't compile | Med | High | Paragraph granularity; a compile failure is just `CONTROL_FLOW` class and re-enters the loop |
| Repair loop oscillates, never converges | Med | High | Patch-hash dedup; K=3 cap; escalation is a *feature*, demo it |
| LLM API slow/down on Aug 12 | Med | Fatal | `--replay` cache, recorded backup video, phone hotspot |
| Docker won't run on venue machine | Low | Fatal | Use your own laptop; test on Aug 12 morning; video fallback |
| "Isn't this watsonx Code Assistant for Z?" | High | Medium | Prepared answer: those translate and hand a human the validation burden. We close the loop autonomously and get cheaper per defect as we run. |
| "Your fixture is a toy" | High | Medium | Agree immediately, then: "Yes — and the six constructs in it are the six that cause the most silent production defects. The mechanism doesn't care about program size; the oracle scales with it." |
| Team overruns on UI | Med | Med | Terminal UI is the deliverable. Web UI is bonus. Enforced at M5. |

---

## 11. Cut List — In Order

When you fall behind (you will), cut from the top:

1. Web UI graph view → coloured terminal output
2. ProLeap ASG → regex extraction
3. FEECALC / memory-reuse demo → describe it on a slide, show the schema
4. Dataflow analysis → pass whole WORKING-STORAGE as context
5. Fuzzer → 20 handwritten test vectors
6. `CONTROL_FLOW` repair class → always escalate that class

**Never cut:** the differential runner, one working repair cycle, the baseline comparison. Those three *are* the project.

---

## 12. Minimum Viable Demo

Define done now, so a bad week still ends in a working demo:

> One COBOL program. One naive LLM translation producing a wrong number. The differential runner catching it. One repair cycle turning it green. Terminal output only.

Two days, one person. If everything else fails, this still wins a room — because the idea is legible in 90 seconds and nobody else will have run their legacy binary.

---

## 13. Roles

| Dev | Owns | Aug 12 job |
|---|---|---|
| A | Fixtures, COBOL, Docker, orchestrator | Drives keyboard during demo |
| B | Perception, generation, repair, memory | Answers technical Q&A |
| C | Differential runner, fuzzer, classification, metrics | Backup driver |
| D | Deck, UI, narration, video | **Narrates.** Starts rehearsing Aug 11, not Aug 12. |
