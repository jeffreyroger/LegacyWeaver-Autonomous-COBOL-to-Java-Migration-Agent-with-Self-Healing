"""Task 6 fixture acceptance test -- migration-framework-spec.md Section 5,
FR-13.4. golden_multiprog.out was produced by actually compiling and
running fixtures/cobol/multiprog/{root,leaf_a,leaf_b}.cob under GnuCOBOL
3.2.0 (via WSL, this Windows dev machine has no native cobc on PATH) against
fixtures/data/multiprog/accounts.dat -- never hand-typed. This checksum is
now this fixture's own frozen number (CLAUDE.md rule 6 discipline).
"""

import hashlib
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "data" / "expected" / "golden_multiprog.out"
EXPECTED_CHECKSUM = "792705f356d0f4262c1c3fe0fabb3f8ca7cc408505e9e6b14776cfe92db6ac7f"


def test_golden_multiprog_checksum_is_stable():
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == EXPECTED_CHECKSUM


def test_leaf_programs_have_no_outgoing_call():
    multiprog_dir = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"
    for name in ("leaf_a.cob", "leaf_b.cob"):
        code_lines = [
            line for line in (multiprog_dir / name).read_text().upper().splitlines()
            if not line.strip().startswith("*")
        ]
        code = "\n".join(code_lines).replace("PROCEDURE DIVISION USING", "")
        assert "CALL " not in code


def test_root_calls_both_leaves():
    multiprog_dir = Path(__file__).resolve().parent.parent / "fixtures" / "cobol" / "multiprog"
    source = (multiprog_dir / "root.cob").read_text().upper()
    assert 'CALL "LEAF-A"' in source
    assert 'CALL "LEAF-B"' in source
