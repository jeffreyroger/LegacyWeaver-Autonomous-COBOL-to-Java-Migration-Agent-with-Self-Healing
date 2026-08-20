"""Phase X7 final end-to-end proof (docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md
X7) -- ROOT.cob's synthesized PROCESS-RECORD body, produced by real
unassisted local Ollama synthesis, correctly resolves its two
`CALL "LEAF-A"`/`CALL "LEAF-B"` statements to real Java method calls
against LEAF-A/LEAF-B's already-committed, verified translations
(reusing the exact hand-verified-correct bodies Phase X3's own tests
established). `weaver verify`'s own comparison machinery
(weaver.comparison.compare_lines) does the final byte-for-byte check of
the assembled 3-program Java translation against golden_multiprog.out
(Task 6's already-frozen number).

Scope note, disclosed rather than hidden: this test drives its own small
synthesis loop (weaver/agent/root_prompt.py's call-aware prompt +
InferenceClient + validate.py's existing pieces) rather than the full
Orchestrator/repair-loop machinery -- wiring this into a permanent,
production Orchestrator path (with repair, memory, escalation) is further
work beyond this stretch phase's own exit criteria, which asks only for
one real, working, disclosed proof that CALL-resolution synthesis is
possible and verifiably correct.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import requests

from weaver.agent.assemble import assemble
from weaver.agent.data_context import build_context
from weaver.agent.inference import InferenceClient, InferenceRequest
from weaver.agent.prompt import SYNTHESIS_SCHEMA
from weaver.agent.root_prompt import allowed_identifiers_with_calls, build_call_aware_prompt
from weaver.agent.scaffold import generate as generate_scaffold, java_signature as scaffold_java_signature
from weaver.agent.segment import segment
from weaver.agent.subprogram_scaffold import generate as generate_subprogram_scaffold
from weaver.agent.validate import auto_qualify, parse_response, static_reject
from weaver.cobol.frontend import load_program, to_scaffold_spec
from weaver.cobol.subprogram import load_subprogram
from weaver import comparison

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"
GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "data" / "expected" / "golden_multiprog.out"
ACCOUNTS = Path(__file__).resolve().parent.parent / "fixtures" / "data" / "multiprog" / "accounts.dat"

# The exact hand-verified-correct bodies Phase X3's own tests established
# (tests/test_subprogram_verify.py: zero divergences against real cobc
# output over all 6 witnesses) -- reused here, not re-derived.
LEAF_A_BODY = "        return input.multiply(java.math.BigDecimal.valueOf(2));"
LEAF_B_BODY = "        return input.add(java.math.BigDecimal.valueOf(10.00));"


def _ollama_reachable() -> bool:
    try:
        r = requests.post("http://127.0.0.1:11434/api/generate",
                           json={"model": "qwen2.5-coder:7b", "prompt": "reply OK", "stream": False}, timeout=20)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


requires_full_stack = pytest.mark.skipif(
    shutil.which("javac") is None or not _ollama_reachable(),
    reason="requires javac on PATH and a working Ollama /api/generate",
)


def _synthesize_root_process_record(max_attempts: int = 4) -> str:
    """Real, unassisted synthesis of ROOT.cob's PROCESS-RECORD body,
    resolving its two CALL statements to LeafA.mainPara/LeafB.mainPara."""
    root_model = load_program(FIXTURE_DIR / "root.cob")
    spec = to_scaffold_spec(root_model)
    paragraphs = {p.identifier: p for p in segment((FIXTURE_DIR / "root.cob").read_text(encoding="utf-8"))}
    paragraph = paragraphs[root_model.paragraph_id]

    context = build_context(paragraph, spec)
    java_sig = scaffold_java_signature(spec)
    external_calls = {
        "LEAF-A": ("LeafA", "static java.math.BigDecimal mainPara(java.math.BigDecimal input)"),
        "LEAF-B": ("LeafB", "static java.math.BigDecimal mainPara(java.math.BigDecimal input)"),
    }
    allowed = allowed_identifiers_with_calls(external_calls)
    prompt = build_call_aware_prompt(paragraph, context, java_sig, spec, external_calls)

    client = InferenceClient(cache_dir=Path("generated/model_cache"),
                              provider=os.environ.get("WEAVER_INFERENCE_PROVIDER", "ollama"))

    last_error = None
    for attempt in range(1, max_attempts + 1):
        this_prompt = prompt if attempt == 1 else f"{prompt}\n\nYour previous answer was rejected: {last_error}. Fix it."
        response = client.generate(InferenceRequest(prompt=this_prompt, schema=SYNTHESIS_SCHEMA))
        try:
            body = parse_response(response.text)
            body.method_body, _ = auto_qualify(body.method_body)
            static_reject(body, allowed)
            return body.method_body
        except Exception as e:  # noqa: BLE001 -- any validation failure just retries
            last_error = e
            continue
    raise AssertionError(f"synthesis did not produce a valid body in {max_attempts} attempts: {last_error}")


@requires_full_stack
def test_root_synthesized_body_resolves_calls_and_matches_golden_output(tmp_path):
    root_body = _synthesize_root_process_record()

    # LeafA/LeafB.java, with their already-committed correct bodies.
    leaf_a_model = load_subprogram(FIXTURE_DIR / "leaf_a.cob")
    leaf_b_model = load_subprogram(FIXTURE_DIR / "leaf_b.cob")
    (tmp_path / "LeafA.java").write_text(generate_subprogram_scaffold(leaf_a_model, LEAF_A_BODY), encoding="utf-8")
    (tmp_path / "LeafB.java").write_text(generate_subprogram_scaffold(leaf_b_model, LEAF_B_BODY), encoding="utf-8")

    # Scaffold.java, assembled with the real synthesized PROCESS-RECORD body.
    root_model = load_program(FIXTURE_DIR / "root.cob")
    spec = to_scaffold_spec(root_model)
    scaffold_source = generate_scaffold(spec)
    assembled = assemble(scaffold_source, {root_model.paragraph_id: root_body})
    (tmp_path / "Scaffold.java").write_text(assembled, encoding="utf-8")

    build_dir = tmp_path / "build"
    result = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(build_dir),
         str(tmp_path / "LeafA.java"), str(tmp_path / "LeafB.java"), str(tmp_path / "Scaffold.java")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"javac failed:\nSynthesized body:\n{root_body}\n\n{result.stdout}\n{result.stderr}"

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy2(ACCOUNTS, run_dir / "accounts.dat")
    run_result = subprocess.run(
        ["java", "-cp", str(build_dir), "Scaffold"],
        cwd=run_dir, capture_output=True, text=True, timeout=30,
    )
    assert run_result.returncode == 0, f"java run failed:\n{run_result.stdout}\n{run_result.stderr}"

    candidate_output = (run_dir / "multiprog.out").read_text(encoding="utf-8")
    golden_text = comparison.normalize_line_endings(GOLDEN.read_text(encoding="utf-8"))
    candidate_text = comparison.normalize_line_endings(candidate_output)

    golden_lines = golden_text.splitlines()
    candidate_lines = candidate_text.splitlines()
    assert len(candidate_lines) == len(golden_lines), (root_body, candidate_text)

    divergences = [
        comparison.compare_lines(i, g, c, None, layout=spec.report_layout)
        for i, (g, c) in enumerate(zip(golden_lines, candidate_lines))
    ]
    divergences = [d for d in divergences if d is not None]
    assert divergences == [], (root_body, divergences)
