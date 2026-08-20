"""Phase AA2 acceptance tests (migration-framework-spec.md Section 3.2's
stronger claim -- application-wide Class Designer dedup across modules).

weaver.agent.class_designer.discover_shared_layouts is proven against this
repo's REAL fixtures directory, not a synthetic example: fixtures/cobol_billfee/
billfee.cob was added specifically for this phase and COPYs the same
FEE-REC.cpy copybook fixtures/cobol_feecalc/feecalc.cob already uses, so
their input layouts are byte-for-byte identical by real construction. The
scan also independently discovers that 8 of this repo's existing programs
already share an identical TOTALS-LINE shape -- not staged, a real finding.
"""

from pathlib import Path

import pytest

from weaver.agent.class_designer import discover_shared_layouts, layout_signature
from weaver.agent.shared_class_codegen import generate_shared_helpers, generate_shared_record_class
from weaver.cobol.frontend import load_program, to_scaffold_spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_identical_layouts_have_identical_signatures():
    feecalc = load_program(FIXTURES / "cobol_feecalc" / "feecalc.cob")
    billfee = load_program(FIXTURES / "cobol_billfee" / "billfee.cob")
    spec_a, spec_b = to_scaffold_spec(feecalc), to_scaffold_spec(billfee)
    assert layout_signature(spec_a.input_layout) == layout_signature(spec_b.input_layout)


def test_discover_shared_layouts_finds_the_real_copybook_sharing_pair():
    plan = discover_shared_layouts(FIXTURES)
    fr_shared = next((s for s in plan.shared if "FR-ID" in [f.name for f in s.layout]), None)
    assert fr_shared is not None, [s.class_name for s in plan.shared]
    program_ids = {u.program_id for u in fr_shared.used_by}
    assert program_ids == {"FEECALC", "BILLFEE"}
    assert all(u.layout_kind == "input_layout" for u in fr_shared.used_by)


def test_discover_shared_layouts_finds_the_widespread_totals_line_dedup():
    """Not staged for this test -- an independent finding: this repo's
    existing programs already share an identical TL-LABEL/TL-TOTAL/
    TL-FILLER totals layout, unrelated to the billfee.cob fixture."""
    plan = discover_shared_layouts(FIXTURES)
    totals_shared = [s for s in plan.shared if {f.name for f in s.layout} == {"TL-LABEL", "TL-TOTAL", "TL-FILLER"}]
    assert len(totals_shared) == 1
    assert len(totals_shared[0].used_by) >= 5


def test_shared_layouts_never_include_a_single_program_use():
    plan = discover_shared_layouts(FIXTURES)
    for shared in plan.shared:
        assert len({u.program_id for u in shared.used_by}) >= 2


def test_colliding_base_class_names_get_disambiguated():
    plan = discover_shared_layouts(FIXTURES)
    names = [s.class_name for s in plan.shared]
    assert len(names) == len(set(names)), f"duplicate class names: {names}"


def test_unsupported_program_shapes_are_skipped_not_crashed():
    # fixtures/cobol/multiprog/*.cob and fixtures/cobol/mocked/*.cob are
    # subprograms/mocked shapes -- outside load_program's file-based scope.
    plan = discover_shared_layouts(FIXTURES)
    skipped_names = {Path(p).name for p in plan.skipped}
    assert "leaf_a.cob" in skipped_names
    assert "billing.cob" in skipped_names


requires_javac = pytest.mark.skipif(__import__("shutil").which("javac") is None, reason="requires javac on PATH")


@requires_javac
def test_shared_input_class_decodes_a_real_record(tmp_path):
    """input_layout classes only ever DECODE in this harness (matching
    weaver/agent/scaffold.py's own AccountRecord, which has no encode()) --
    an earlier version of shared_class_codegen.py emitted encode() for
    every layout kind unconditionally, which crashed on any signed
    floating-sign report/totals field (found during the 2026-08-20
    validation pass); this asserts the corrected, kind-aware behavior."""
    plan = discover_shared_layouts(FIXTURES)
    fr_shared = next(s for s in plan.shared if "FR-ID" in [f.name for f in s.layout])
    assert fr_shared.layout_kind == "input_layout"

    source = generate_shared_record_class(fr_shared.class_name, fr_shared.layout, fr_shared.layout_kind)
    assert "encode()" not in source
    (tmp_path / f"{fr_shared.class_name}.java").write_text(source, encoding="utf-8")
    (tmp_path / "CobolShared.java").write_text(generate_shared_helpers(), encoding="utf-8")

    main_source = f"""\
public final class Main {{
    public static void main(String[] args) {{
        String line = "ACCT000000000001" + "00012345678" + "-" + "A" + "Y";
        {fr_shared.class_name} r = {fr_shared.class_name}.decode(line);
        System.out.println(r.id + "|" + r.balance + "|" + r.tier + "|" + r.active);
    }}
}}
"""
    (tmp_path / "Main.java").write_text(main_source, encoding="utf-8")

    import subprocess
    compiled = subprocess.run(
        ["javac", "-d", str(tmp_path), f"{fr_shared.class_name}.java", "CobolShared.java", "Main.java"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"

    ran = subprocess.run(["java", "-cp", str(tmp_path), "Main"], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "ACCT000000000001|-123456.78|A|Y"


@requires_javac
def test_shared_totals_class_has_no_decode_and_encodes_correctly(tmp_path):
    plan = discover_shared_layouts(FIXTURES)
    tl_shared = next(s for s in plan.shared if {f.name for f in s.layout} == {"TL-LABEL", "TL-TOTAL", "TL-FILLER"})
    assert tl_shared.layout_kind == "totals_layout"

    source = generate_shared_record_class(tl_shared.class_name, tl_shared.layout, tl_shared.layout_kind)
    assert "decode(" not in source
    (tmp_path / f"{tl_shared.class_name}.java").write_text(source, encoding="utf-8")
    (tmp_path / "CobolShared.java").write_text(generate_shared_helpers(), encoding="utf-8")

    main_source = f"""\
public final class Main {{
    public static void main(String[] args) {{
        {tl_shared.class_name} t = new {tl_shared.class_name}("TOTAL:", new java.math.BigDecimal("-1234.56"), " ");
        System.out.println(t.encode());
    }}
}}
"""
    (tmp_path / "Main.java").write_text(main_source, encoding="utf-8")

    import subprocess
    compiled = subprocess.run(
        ["javac", "-d", str(tmp_path), f"{tl_shared.class_name}.java", "CobolShared.java", "Main.java"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"

    ran = subprocess.run(["java", "-cp", str(tmp_path), "Main"], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    assert "-1234.56" in ran.stdout


@requires_javac
def test_every_discovered_shared_class_compiles_together_in_one_batch(tmp_path):
    """Regression test for a real bug found during the 2026-08-20
    validation pass: generate_shared_record_class used to inline the
    CobolDecode/CobolEdit helper source into EVERY generated file, which
    compiled fine for exactly one class in isolation but failed with
    "javac: duplicate class: CobolEdit" the moment two or more shared
    classes were compiled together -- the realistic case, since a real
    migration wants every discovered shared class available at once."""
    plan = discover_shared_layouts(FIXTURES)
    assert len(plan.shared) >= 2  # otherwise this test can't exercise the collision

    (tmp_path / "CobolShared.java").write_text(generate_shared_helpers(), encoding="utf-8")
    filenames = ["CobolShared.java"]
    for shared in plan.shared:
        source = generate_shared_record_class(shared.class_name, shared.layout, shared.layout_kind)
        (tmp_path / f"{shared.class_name}.java").write_text(source, encoding="utf-8")
        filenames.append(f"{shared.class_name}.java")

    import subprocess
    compiled = subprocess.run(
        ["javac", "-d", str(tmp_path), *filenames], cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert compiled.returncode == 0, f"{compiled.stdout}\n{compiled.stderr}"
