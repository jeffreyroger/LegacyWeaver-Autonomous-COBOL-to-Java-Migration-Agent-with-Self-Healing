"""Phase AA1 acceptance tests -- weaver.agent.batch_synthesize drives
weaver.agent.hierarchical_segment's blocks through one scripted LLM call
per block (fake client, same convention tests/test_repair_loop.py uses --
no live model needed to exercise the real control flow), proving leaf-first
ordering reaches the prompt as "already translated" context, and that the
merged result feeds the real, unmodified weaver.agent.assemble.assemble()
to produce a real javac-compilable Java class."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from weaver.agent.assemble import assemble
from weaver.agent.batch_synthesize import BatchValidationError, parse_batch_response, synthesize_hierarchical
from weaver.agent.inference import InferenceResponse
from weaver.agent.segment import Paragraph, segment
from weaver.agent.validate import ValidationError

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "hierarchical" / "big_program.cob"


class _ScriptedBatchClient:
    """Returns bodies keyed by paragraph id, scripted per block call, in
    the order blocks are actually requested -- asserts the caller never
    asks for more calls than scripted."""

    def __init__(self, responses_by_call: list[dict[str, str]]):
        self._responses = list(responses_by_call)
        self.prompts: list[str] = []

    def generate(self, request) -> InferenceResponse:
        self.prompts.append(request.prompt)
        if not self._responses:
            raise AssertionError("model called more times than the test scripted")
        bodies = self._responses.pop(0)
        text = json.dumps({"bodies": bodies, "assumptions": []})
        return InferenceResponse(text=text, eval_count=0, eval_duration_ns=0, from_cache=False)


def _paragraphs():
    return segment(FIXTURE.read_text(encoding="utf-8"))


def test_parse_batch_response_requires_every_expected_id():
    text = json.dumps({"bodies": {"A": "x;"}, "assumptions": []})
    with pytest.raises(BatchValidationError):
        parse_batch_response(text, ["A", "B"])


def test_parse_batch_response_rejects_unexpected_extra_id():
    text = json.dumps({"bodies": {"A": "x;", "C": "y;"}, "assumptions": []})
    with pytest.raises(BatchValidationError):
        parse_batch_response(text, ["A"])


def test_parse_batch_response_happy_path():
    text = json.dumps({"bodies": {"A": "x;", "B": "y;"}, "assumptions": []})
    assert parse_batch_response(text, ["A", "B"]) == {"A": "x;", "B": "y;"}


def test_synthesize_hierarchical_processes_blocks_leaf_first_with_growing_context():
    paras = _paragraphs()
    # 4 blocks under budget 3 (same shape proven in test_hierarchical_segment.py).
    # TRACE.add(...) is a single-dot call ("TRACE" is an explicitly allowed
    # identifier below) -- avoids validate.py's static_reject treating the
    # middle segment of a 3-part chain like System.out.println as an
    # unqualified reference (a real, pre-existing quirk of that hardened
    # regex this test does not exercise on purpose).
    responses = [
        {"PARA-D": 'TRACE.add("D");', "PARA-E": 'TRACE.add("E");'},
        {"PARA-F": 'TRACE.add("F");', "PARA-G": 'TRACE.add("G");'},
        {"PARA-H": 'TRACE.add("H");', "PARA-A": "paraE(); paraF();"},
        {"PARA-B": "paraG();", "PARA-C": "paraH();", "MAIN-PARA": "paraA(); paraB(); paraC(); paraD();"},
    ]
    client = _ScriptedBatchClient(responses)
    result = synthesize_hierarchical(paras, client, ws_fields=[], max_paragraphs_per_block=3,
                                      max_lines_per_block=1000, allowed_identifiers={"TRACE"})

    assert not result.had_cycle
    assert set(result.bodies) == {p.identifier for p in paras}
    assert len(client.prompts) == 4

    # The block translating PARA-A (3rd call) must have been told PARA-E
    # and PARA-F's method names -- real "topological call rankings" context.
    third_prompt = client.prompts[2]
    assert "paraE" in third_prompt
    assert "paraF" in third_prompt
    # The FIRST block's prompt has no prior context (nothing translated yet).
    assert "none yet" in client.prompts[0]


def test_synthesize_hierarchical_rejects_a_body_referencing_a_disallowed_object():
    paras = [Paragraph("ONLY-PARA", 1, 1, "ONLY-PARA.\n    DISPLAY 1.\n")]
    client = _ScriptedBatchClient([{"ONLY-PARA": "int x = evilObject.hack();"}])
    with pytest.raises(ValidationError):
        synthesize_hierarchical(paras, client, ws_fields=["balance"])


requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_merged_bodies_assemble_into_real_compilable_java(tmp_path):
    """Real end-to-end proof of "segment -> translate -> merge": every
    paragraph's hierarchically-synthesized body is spliced into a
    hand-written multi-marker scaffold via the real, unmodified
    weaver.agent.assemble.assemble(), and the result is real javac-compiled."""
    paras = _paragraphs()
    responses = [
        {"PARA-D": 'TRACE.add("D");', "PARA-E": 'TRACE.add("E");'},
        {"PARA-F": 'TRACE.add("F");', "PARA-G": 'TRACE.add("G");'},
        {"PARA-H": 'TRACE.add("H");', "PARA-A": "paraE(); paraF();"},
        {"PARA-B": "paraG();", "PARA-C": "paraH();", "MAIN-PARA": "paraA(); paraB(); paraC(); paraD();"},
    ]
    client = _ScriptedBatchClient(responses)
    result = synthesize_hierarchical(paras, client, ws_fields=[], max_paragraphs_per_block=3,
                                      max_lines_per_block=1000, allowed_identifiers={"TRACE"})

    scaffold = (
        "import java.util.List;\n"
        "import java.util.ArrayList;\n"
        "public final class BigProg {\n"
        "    static final List<String> TRACE = new ArrayList<>();\n"
    )
    for p in paras:
        method = result.method_names[p.identifier]
        scaffold += (
            f"    void {method}() {{\n"
            f"        // PARAGRAPH:{p.identifier}:BEGIN\n"
            f"        // (stub)\n"
            f"        // PARAGRAPH:{p.identifier}:END\n"
            f"    }}\n"
        )
    scaffold += (
        "    public static void main(String[] args) {\n"
        "        new BigProg().mainPara();\n"
        "        System.out.println(String.join(\" \", TRACE));\n"
        "    }\n"
        "}\n"
    )

    assembled = assemble(scaffold, result.bodies)
    java_file = tmp_path / "BigProg.java"
    java_file.write_text(assembled, encoding="utf-8")

    compile_result = subprocess.run(
        ["javac", "-d", str(tmp_path), str(java_file)], capture_output=True, text=True, timeout=30,
    )
    assert compile_result.returncode == 0, f"javac failed:\n{compile_result.stdout}\n{compile_result.stderr}\n\n{assembled}"

    run_result = subprocess.run(
        ["java", "-cp", str(tmp_path), "BigProg"], capture_output=True, text=True, timeout=30,
    )
    assert run_result.returncode == 0, run_result.stderr
    assert run_result.stdout.split() == ["E", "F", "G", "H", "D"]
