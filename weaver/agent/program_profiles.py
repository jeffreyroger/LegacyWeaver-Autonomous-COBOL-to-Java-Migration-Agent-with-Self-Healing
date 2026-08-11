"""Per-program overrides shared by `weaver verify`/`weaver migrate` (weaver/cli.py)
and the backend run service (backend/runs.py) — moved out of cli.py
(2026-08-12) so backend/runs.py can resolve the same scaffold_path/
golden_output/scaffold_spec a CLI-launched run would use, instead of
silently defaulting to interest.cob's for every program (the same DC-5/
NFR-D1 defect class as CLAUDE.md hard rule 13's data_file bug, found in
the 2026-08-12 audit). No CLI-only dependencies (argparse, rich) live
here so backend/runs.py doesn't have to pull them in.
"""

from __future__ import annotations

from pathlib import Path


class ProgramProfile:
    """Per-program overrides `weaver verify`/`weaver migrate`/the backend
    need beyond the CLI's interest-specific defaults -- report/totals
    layout for field resolution (NFR-14: a second fixture needs no code
    change, only data), output filename, and the agent-layer paths a
    second program's ScaffoldSpec already produces (Step S1)."""

    def __init__(self, report_layout, totals_layout, output_filename, *,
                 scaffold_path=None, golden_output=None, reference_body_path=None,
                 reference_paragraph_id=None, input_data=None, scaffold_spec=None):
        self.report_layout = report_layout
        self.totals_layout = totals_layout
        self.output_filename = output_filename
        self.scaffold_path = scaffold_path
        self.golden_output = golden_output
        self.reference_body_path = reference_body_path
        self.reference_paragraph_id = reference_paragraph_id
        self.input_data = input_data
        # Field/accessor/signature tables the synthesis/repair prompts derive
        # their per-program content from (generalized post-S1: these were
        # previously hardcoded to interest.cob throughout weaver/agent/, so
        # a second program's synthesis prompt silently described interest's
        # fields -- see weaver/agent/scaffold.py's ScaffoldSpec).
        self.scaffold_spec = scaffold_spec


def _feecalc_profile() -> ProgramProfile:
    # Imported lazily so a plain `weaver verify` on interest.cob never pays
    # for loading the second program's modules.
    from weaver.agent import feecalc_layout
    from weaver.agent.feecalc_spec import FEECALC_SPEC
    return ProgramProfile(
        report_layout=feecalc_layout.REPORT_LAYOUT,
        totals_layout=feecalc_layout.TOTALS_LAYOUT,
        output_filename="fee.out",
        scaffold_path=Path("generated/feecalc/Scaffold.java"),
        golden_output=Path("fixtures/data_feecalc/expected/golden_feecalc.out"),
        reference_body_path=Path("reference_feecalc/compute_fee.body.java"),
        reference_paragraph_id=FEECALC_SPEC.paragraph_id,
        input_data=Path("fixtures/data_feecalc/fees.dat"),
        scaffold_spec=FEECALC_SPEC,
    )


def _taxcalc_profile() -> ProgramProfile:
    # Step U1 -- nested IF/ELSE bracket ladder, a different control-flow
    # shape from feecalc.cob's flat EVALUATE lookup.
    from weaver.agent import taxcalc_layout
    from weaver.agent.taxcalc_spec import TAXCALC_SPEC
    return ProgramProfile(
        report_layout=taxcalc_layout.REPORT_LAYOUT,
        totals_layout=taxcalc_layout.TOTALS_LAYOUT,
        output_filename="tax.out",
        scaffold_path=Path("generated/taxcalc/Scaffold.java"),
        golden_output=Path("fixtures/data_taxcalc/expected/golden_taxcalc.out"),
        reference_body_path=Path("reference_taxcalc/compute_tax.body.java"),
        reference_paragraph_id=TAXCALC_SPEC.paragraph_id,
        input_data=Path("fixtures/data_taxcalc/tax.dat"),
        scaffold_spec=TAXCALC_SPEC,
    )


def _tieraccum_profile() -> ProgramProfile:
    # Step U2 -- an in-paragraph PERFORM VARYING loop, a different
    # control-flow shape from every other fixture's per-record-only loop.
    from weaver.agent import tieraccum_layout
    from weaver.agent.tieraccum_spec import TIERACCUM_SPEC
    return ProgramProfile(
        report_layout=tieraccum_layout.REPORT_LAYOUT,
        totals_layout=tieraccum_layout.TOTALS_LAYOUT,
        output_filename="tieraccum.out",
        scaffold_path=Path("generated/tieraccum/Scaffold.java"),
        golden_output=Path("fixtures/data_tieraccum/expected/golden_tieraccum.out"),
        reference_body_path=Path("reference_tieraccum/accumulate_tiers.body.java"),
        reference_paragraph_id=TIERACCUM_SPEC.paragraph_id,
        input_data=Path("fixtures/data_tieraccum/tieraccum.dat"),
        scaffold_spec=TIERACCUM_SPEC,
    )


def _compound_profile() -> ProgramProfile:
    # Step U3 -- a straight-line chain of COMPUTE statements, no
    # branching or looping at all.
    from weaver.agent import compound_layout
    from weaver.agent.compound_spec import COMPOUND_SPEC
    return ProgramProfile(
        report_layout=compound_layout.REPORT_LAYOUT,
        totals_layout=compound_layout.TOTALS_LAYOUT,
        output_filename="compound.out",
        scaffold_path=Path("generated/compound/Scaffold.java"),
        golden_output=Path("fixtures/data_compound/expected/golden_compound.out"),
        reference_body_path=Path("reference_compound/compute_compound.body.java"),
        reference_paragraph_id=COMPOUND_SPEC.paragraph_id,
        input_data=Path("fixtures/data_compound/compound.dat"),
        scaffold_spec=COMPOUND_SPEC,
    )


def _shipcost_profile() -> ProgramProfile:
    # Step U4 -- EVALUATE TRUE with a compound AND condition spanning two
    # input fields, a different lookup shape from feecalc.cob/taxcalc.cob.
    from weaver.agent import shipcost_layout
    from weaver.agent.shipcost_spec import SHIPCOST_SPEC
    return ProgramProfile(
        report_layout=shipcost_layout.REPORT_LAYOUT,
        totals_layout=shipcost_layout.TOTALS_LAYOUT,
        output_filename="shipcost.out",
        scaffold_path=Path("generated/shipcost/Scaffold.java"),
        golden_output=Path("fixtures/data_shipcost/expected/golden_shipcost.out"),
        reference_body_path=Path("reference_shipcost/compute_shipcost.body.java"),
        reference_paragraph_id=SHIPCOST_SPEC.paragraph_id,
        input_data=Path("fixtures/data_shipcost/shipcost.dat"),
        scaffold_spec=SHIPCOST_SPEC,
    )


# Matched against the COBOL source's filename, not its full path, so the
# fixture can move without breaking this lookup.
PROGRAM_PROFILES: dict[str, ProgramProfile] = {
    "feecalc.cob": _feecalc_profile,
    "taxcalc.cob": _taxcalc_profile,
    "tieraccum.cob": _tieraccum_profile,
    "compound.cob": _compound_profile,
    "shipcost.cob": _shipcost_profile,
}


def program_profile(cobol_source: Path) -> ProgramProfile | None:
    factory = PROGRAM_PROFILES.get(cobol_source.name)
    return factory() if factory else None
