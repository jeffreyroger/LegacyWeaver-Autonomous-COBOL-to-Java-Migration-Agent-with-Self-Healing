"""Per-program overrides shared by `zuse verify`/`zuse migrate` (zuse/cli.py)
and the backend run service (backend/runs.py) — moved out of cli.py
(2026-08-12) so backend/runs.py can resolve the same scaffold_path/
golden_output/scaffold_spec a CLI-launched run would use, instead of
silently defaulting to interest.cob's for every program (the same DC-5/
NFR-D1 defect class as CLAUDE.md hard rule 13's data_file bug, found in
the 2026-08-12 audit). No CLI-only dependencies (argparse, rich) live
here so backend/runs.py doesn't have to pull them in.

**Phase V (2026-08-12).** Everything this module used to import from a
hand-written pair of modules per program — `report_layout`, `totals_layout`,
`output_filename`, `scaffold_spec`, `reference_paragraph_id` — is now parsed
from the COBOL source by `zuse/cobol/`. What remains declared here is the
one category that genuinely is not in the COBOL: **where this repository
keeps a program's artefacts** (its scaffold, golden output, reference body
and input data). Those are project layout decisions, not facts about the
program, so they stay data.

Consequence worth knowing: a program with no entry in `_PROGRAM_PATHS` still
resolves correct layouts and a correct `ScaffoldSpec`, so `zuse verify`
works on it with no code change at all. Only `zuse migrate`, which needs
somewhere to put artefacts and a golden output to verify against, needs an
entry added.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zuse.cobol.frontend import load_program_cached, to_scaffold_spec


@dataclass(frozen=True)
class ProgramPaths:
    """Where this repo keeps one program's artefacts. Not derivable from
    COBOL — `fees.dat` lives under `zuse/examples/input/data/` because someone
    decided it should, not because feecalc.cob says so."""

    scaffold_path: Path
    golden_output: Path
    reference_dir: Path
    data_dir: Path


# Keyed on the COBOL source's filename, not its full path, so a fixture can
# move without breaking the lookup.
_PROGRAM_PATHS: dict[str, ProgramPaths] = {
    "feecalc.cob": ProgramPaths(
        Path("zuse/examples/generated/feecalc/Scaffold.java"),
        Path("zuse/examples/reference_feecalc/fee.out"),
        Path("zuse/examples/reference_feecalc"),
        Path("zuse/examples/input/data"),
    ),
    "taxcalc.cob": ProgramPaths(
        Path("zuse/examples/generated/taxcalc/Scaffold.java"),
        Path("zuse/examples/reference_taxcalc/golden_taxcalc.out"),
        Path("zuse/examples/reference_taxcalc"),
        Path("zuse/examples/input/data"),
    ),
    "tieraccum.cob": ProgramPaths(
        Path("zuse/examples/generated/tieraccum/Scaffold.java"),
        Path("zuse/examples/reference_tieraccum/golden_tieraccum.out"),
        Path("zuse/examples/reference_tieraccum"),
        Path("zuse/examples/input/data"),
    ),
    "compound.cob": ProgramPaths(
        Path("zuse/examples/generated/compound/Scaffold.java"),
        Path("zuse/examples/reference_compound/golden_compound.out"),
        Path("zuse/examples/reference_compound"),
        Path("zuse/examples/input/data"),
    ),
    "shipcost.cob": ProgramPaths(
        Path("zuse/examples/generated/shipcost/Scaffold.java"),
        Path("zuse/examples/reference_shipcost/golden_shipcost.out"),
        Path("zuse/examples/reference_shipcost"),
        Path("zuse/examples/input/data"),
    ),
    "handlfee.cob": ProgramPaths(
        Path("zuse/examples/generated/handlfee/Scaffold.java"),
        Path("zuse/examples/reference_handlfee/golden_handlfee.out"),
        Path("zuse/examples/reference_handlfee"),
        Path("zuse/examples/input/data"),
    ),
    # interest.cob is deliberately absent: its paths are RunSpec's defaults.
    # asdf.cob/test3.cob are the original (badly-named) WHSEPROC/BANKPROC
    # fixtures under zuse/examples/input/; whseproc.cob/bankproc.cob are the same
    # programs promoted into input/ under their real names (2026-08-12) for
    # Vite/CI use. Both keys point at the same artefacts -- one program, two
    # filenames it's known by in this repo.
    "asdf.cob": ProgramPaths(
        Path("zuse/examples/generated/whseproc/Scaffold.java"),
        Path("zuse/examples/reference_whseproc/golden_whseproc.out"),
        Path("zuse/examples/reference_whseproc"),
        Path("zuse/examples/input/data"),
    ),
    "test3.cob": ProgramPaths(
        Path("zuse/examples/generated/bankproc/Scaffold.java"),
        Path("zuse/examples/reference_bankproc/golden_bankproc.out"),
        Path("zuse/examples/reference_bankproc"),
        Path("zuse/examples/input/data"),
    ),
    "whseproc.cob": ProgramPaths(
        Path("zuse/examples/generated/whseproc/Scaffold.java"),
        Path("zuse/examples/reference_whseproc/golden_whseproc.out"),
        Path("zuse/examples/reference_whseproc"),
        Path("zuse/examples/input/data"),
    ),
    "bankproc.cob": ProgramPaths(
        Path("zuse/examples/generated/bankproc/Scaffold.java"),
        Path("zuse/examples/reference_bankproc/golden_bankproc.out"),
        Path("zuse/examples/reference_bankproc"),
        Path("zuse/examples/input/data"),
    ),
}


class ProgramProfile:
    """Per-program values `zuse verify`/`zuse migrate`/the backend need
    beyond RunSpec's interest-specific defaults. Layouts, output filename and
    `ScaffoldSpec` are derived from the COBOL source (NFR-14: a second
    fixture needs no code change — now not even a data change); paths come
    from `_PROGRAM_PATHS` when the program has an entry."""

    def __init__(
        self,
        report_layout,
        totals_layout,
        output_filename,
        *,
        scaffold_path=None,
        golden_output=None,
        reference_body_path=None,
        reference_paragraph_id=None,
        input_data=None,
        scaffold_spec=None,
    ):
        self.report_layout = report_layout
        self.totals_layout = totals_layout
        self.output_filename = output_filename
        self.scaffold_path = scaffold_path
        self.golden_output = golden_output
        self.reference_body_path = reference_body_path
        self.reference_paragraph_id = reference_paragraph_id
        self.input_data = input_data
        self.scaffold_spec = scaffold_spec


def _reference_body_path(reference_dir: Path, paragraph_id: str) -> Path:
    """COMPUTE-FEE -> <dir>/compute_fee.body.java."""
    return reference_dir / f"{paragraph_id.lower().replace('-', '_')}.body.java"


def program_profile(
    cobol_source: Path, copybook_dir: Path | None = None
) -> ProgramProfile | None:
    """Resolve one program's profile by parsing it.

    Two distinct failure cases, deliberately handled differently:

    * **Source file absent** -> None. Constructing a `RunSpec` is not the
      right place to reject a path that does not exist; the run fails with a
      clearer message when `cobc`/`javac` reaches it. This is also what lets
      the CLI's argument-plumbing tests use placeholder paths.
    * **Source present but outside the frontend's declared scope** -> raises.
      Returning None there would mean "fall back to interest.cob's layouts",
      which silently slices another program's output with the wrong field
      boundaries — a confident wrong answer, which is the one outcome this
      project exists to prevent.
    """
    cobol_source = Path(cobol_source)
    if not cobol_source.is_file():
        return None

    model = load_program_cached(cobol_source, copybook_dir)
    paths = _PROGRAM_PATHS.get(Path(cobol_source).name)

    return ProgramProfile(
        report_layout=model.report_layout,
        totals_layout=model.totals_layout,
        output_filename=model.output_file,
        scaffold_spec=to_scaffold_spec(model),
        reference_paragraph_id=model.paragraph_id,
        scaffold_path=paths.scaffold_path if paths else None,
        golden_output=paths.golden_output if paths else None,
        reference_body_path=(
            _reference_body_path(paths.reference_dir, model.paragraph_id)
            if paths
            else None
        ),
        # The input file's *name* is in the COBOL (SELECT ... ASSIGN TO);
        # only the directory it lives in is a repo decision.
        input_data=(paths.data_dir / model.input_file) if paths else None,
    )
