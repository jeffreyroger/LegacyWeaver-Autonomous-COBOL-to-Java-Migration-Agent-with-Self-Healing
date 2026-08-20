"""CLI wiring tests for `weaver connectors` (Phase Z2) and `weaver dedup`
(Phase AA2) -- found missing from the test suite during the 2026-08-20
spec-compliance validation pass (both commands worked when invoked by
hand, but neither had a pytest covering `weaver.cli.main`'s actual
argument parsing and dispatch, so a wiring regression -- a typo in the
subcommand name, a swapped argument -- would only have been caught by
someone remembering to run the CLI manually)."""

from pathlib import Path

from weaver.cli import main

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_dedup_cli_finds_shared_layouts_and_writes_files(tmp_path, capsys):
    exit_code = main(["dedup", str(FIXTURES), "--out-dir", str(tmp_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "FrRecord" in out
    assert (tmp_path / "CobolShared.java").exists()
    assert (tmp_path / "FrRecord.java").exists()


def test_dedup_cli_rejects_a_nonexistent_directory(capsys):
    exit_code = main(["dedup", str(FIXTURES / "does_not_exist")])
    assert exit_code == 1
    assert "not a directory" in capsys.readouterr().out


def test_dedup_cli_reports_nothing_found_without_crashing(tmp_path, capsys):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    exit_code = main(["dedup", str(empty_dir), "--out-dir", str(tmp_path / "out")])
    assert exit_code == 0
    assert "No structurally identical" in capsys.readouterr().out


def test_connectors_cli_generates_artefacts_for_a_real_fixture(tmp_path, capsys):
    exit_code = main([
        "connectors", str(FIXTURES / "cobol" / "mocked" / "orders.cob"), "--out-dir", str(tmp_path),
    ])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Generated" in out
    assert (tmp_path / "OfflineAdapters.java").exists()
    assert (tmp_path / "schema.sql").exists()


def test_connectors_cli_reports_no_directives_without_crashing(tmp_path, capsys):
    # LEAF-A has no EXEC SQL/EXEC CICS directives at all.
    exit_code = main([
        "connectors", str(FIXTURES / "cobol" / "multiprog" / "leaf_a.cob"), "--out-dir", str(tmp_path),
    ])
    assert exit_code == 0
    assert "nothing to generate" in capsys.readouterr().out
