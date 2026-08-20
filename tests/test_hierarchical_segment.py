"""Phase AA1 acceptance tests (migration-framework-spec.md Section 3.1) --
weaver.agent.hierarchical_segment's call-graph extraction, leaf-first
topological ordering (including a genuinely cyclic case), and recursive
size-bounded block splitting, proven against a real 9-paragraph fixture
parsed by the real weaver.agent.segment.segment()."""

from pathlib import Path

from weaver.agent.hierarchical_segment import (
    paragraph_call_graph,
    segment_hierarchical,
    topological_paragraph_order,
)
from weaver.agent.segment import Paragraph, segment

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "hierarchical" / "big_program.cob"


def _paragraphs():
    return segment(FIXTURE.read_text(encoding="utf-8"))


def test_call_graph_matches_the_real_fixtures_perform_edges():
    graph = paragraph_call_graph(_paragraphs())
    assert graph["MAIN-PARA"] == frozenset({"PARA-A", "PARA-B", "PARA-C", "PARA-D"})
    assert graph["PARA-A"] == frozenset({"PARA-E", "PARA-F"})
    assert graph["PARA-D"] == frozenset()
    assert graph["PARA-H"] == frozenset()


def test_topological_order_is_leaf_first():
    order = topological_paragraph_order(_paragraphs())
    assert not order.had_cycle
    positions = {pid: i for i, pid in enumerate(order.order)}
    # Every callee strictly precedes every one of its known callers.
    for caller, callees in paragraph_call_graph(_paragraphs()).items():
        for callee in callees:
            assert positions[callee] < positions[caller], (callee, caller)


def test_topological_order_handles_a_real_cycle_deterministically():
    cyclic = [
        Paragraph("X", 1, 1, "X.\n    PERFORM Y.\n"),
        Paragraph("Y", 1, 1, "Y.\n    PERFORM X.\n"),
    ]
    result = topological_paragraph_order(cyclic)
    assert result.had_cycle
    assert set(result.order) == {"X", "Y"}
    # deterministic across repeated calls, not a source of run-to-run drift
    assert topological_paragraph_order(cyclic) == result


def test_segment_hierarchical_respects_the_paragraph_budget():
    blocks = segment_hierarchical(_paragraphs(), max_paragraphs_per_block=3, max_lines_per_block=1000)
    assert all(b.size <= 3 for b in blocks)
    assert len(blocks) > 1
    assert any(b.depth > 0 for b in blocks), "9 paragraphs under budget 3 should force real recursion"


def test_segment_hierarchical_flattened_blocks_equal_the_topological_order():
    paras = _paragraphs()
    blocks = segment_hierarchical(paras, max_paragraphs_per_block=2, max_lines_per_block=1000)
    flattened = [pid for b in blocks for pid in b.paragraph_ids]
    assert flattened == list(topological_paragraph_order(paras).order)


def test_segment_hierarchical_never_splits_a_single_paragraph():
    # A single oversized paragraph still becomes its own one-paragraph
    # block rather than being further divided or raising.
    huge = [Paragraph("HUGE", 1, 1, "HUGE.\n" + "    DISPLAY 1.\n" * 500)]
    blocks = segment_hierarchical(huge, max_paragraphs_per_block=8, max_lines_per_block=10)
    assert len(blocks) == 1
    assert blocks[0].paragraph_ids == ("HUGE",)


def test_segment_hierarchical_fits_everything_in_one_block_when_under_budget():
    blocks = segment_hierarchical(_paragraphs(), max_paragraphs_per_block=20, max_lines_per_block=1000)
    assert len(blocks) == 1
    assert blocks[0].size == 9
    assert blocks[0].depth == 0
