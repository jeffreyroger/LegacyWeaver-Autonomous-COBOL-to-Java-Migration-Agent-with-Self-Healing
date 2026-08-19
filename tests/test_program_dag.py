from pathlib import Path

from weaver.cobol.program_dag import from_directory

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"


def test_from_directory_finds_three_programs():
    dag = from_directory(FIXTURE_DIR)
    assert set(dag.programs) == {"ROOT", "LEAF-A", "LEAF-B"}


def test_edges_reflect_root_calls_both_leaves():
    dag = from_directory(FIXTURE_DIR)
    callers = {e.caller for e in dag.edges}
    callees = {e.callee for e in dag.edges}
    assert callers == {"ROOT"}
    assert callees == {"LEAF-A", "LEAF-B"}


def test_topological_order_is_leaf_first():
    dag = from_directory(FIXTURE_DIR)
    order = dag.topological_order()
    flat = [p for layer in order for p in layer]
    assert flat.index("LEAF-A") < flat.index("ROOT")
    assert flat.index("LEAF-B") < flat.index("ROOT")


def test_leaves_have_no_outgoing_edges():
    dag = from_directory(FIXTURE_DIR)
    callers = {e.caller for e in dag.edges}
    assert "LEAF-A" not in callers
    assert "LEAF-B" not in callers
