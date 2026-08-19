from weaver.agent.segment import Paragraph
from weaver.cobol.reducibility import classify, rewrite


def _para(identifier, source):
    # Paragraph's real constructor (weaver/agent/segment.py) is
    # (identifier, start_line, end_line, source); start_line/end_line are
    # not exercised by this module, so pass placeholder line numbers.
    lines = source.splitlines()
    return Paragraph(identifier=identifier, start_line=1, end_line=len(lines), source=source)


def test_classify_structured_paragraph_with_only_perform():
    p = _para("PROCESS-RECORD", "PROCESS-RECORD.\n    PERFORM VALIDATE-RECORD.\n")
    assert classify(p) == "STRUCTURED"


def test_classify_unstructured_with_goto():
    p = _para("PROCESS-RECORD",
               "PROCESS-RECORD.\n    IF WS-EOF = 'Y' GO TO END-PARA END-IF.\n")
    assert classify(p) == "UNSTRUCTURED"


def test_classify_unresolved_when_target_computed():
    # Represented here as a GO TO into a paragraph this module cannot see
    # (not present in all_paragraphs at rewrite time) -- rewrite() must
    # return None rather than guess.
    p = _para("PROCESS-RECORD", "PROCESS-RECORD.\n    GO TO WS-COMPUTED-TARGET.\n")
    result = rewrite(p, all_paragraphs={})
    assert result is None


def test_rewrite_simple_goto_into_evaluate():
    p = _para("PROCESS-RECORD",
               "PROCESS-RECORD.\n    IF WS-EOF = 'Y'\n        GO TO END-PARA\n    END-IF.\n    MOVE 1 TO WS-X.\nEND-PARA.\n    MOVE 2 TO WS-Y.\n")
    all_paras = {"PROCESS-RECORD": p, "END-PARA": _para("END-PARA", "END-PARA.\n    MOVE 2 TO WS-Y.\n")}
    result = rewrite(p, all_paras)
    assert result is not None
    assert "GO TO" not in result
    assert "EVALUATE" in result


def test_rewrite_returns_source_unchanged_when_no_goto():
    p = _para("PROCESS-RECORD", "PROCESS-RECORD.\n    PERFORM VALIDATE-RECORD.\n")
    result = rewrite(p, all_paragraphs={})
    assert result == p.source
