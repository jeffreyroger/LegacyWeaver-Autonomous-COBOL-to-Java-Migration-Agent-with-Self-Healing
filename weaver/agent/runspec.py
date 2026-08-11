"""The single definition of what parameters constitute a run.

One field per SRS SS3.9.1 `weaver migrate` flag. Before this existed,
scaffold_path was accepted by Orchestrator and never read, the input data
path was a module constant no caller could influence, MAX_ATTEMPTS and SEED
were module constants, and replay_only was unreachable -- so backend/runs.py
recorded a `data_file` in params.json that had no effect on the run
(DC-5 / NFR-D1). Every run parameter now lives here and is threaded
explicitly.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent.scaffold import INTEREST_SPEC, ScaffoldSpec

# Defaults copied verbatim from SRS SS3.9.1.
DEFAULT_MAX_REPAIRS = 3
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_SEED = 42

DEFAULT_COBOL_SOURCE = Path("fixtures/cobol/interest.cob")
DEFAULT_INPUT_DATA = Path("fixtures/data/accounts.dat")
DEFAULT_GOLDEN_OUTPUT = Path("fixtures/data/expected/golden_interest.out")
DEFAULT_SCAFFOLD_PATH = Path("generated/Scaffold.java")
DEFAULT_MEMORY_STORE = Path("generated/failure_memory.json")
DEFAULT_REFERENCE_BODY_PATH = Path("reference/process_record.body.java")
DEFAULT_REFERENCE_PARAGRAPH_ID = "PROCESS-RECORD"


@dataclass(frozen=True)
class RunSpec:
    cobol_source: Path = DEFAULT_COBOL_SOURCE
    copybook_dir: Path | None = None
    input_data: Path = DEFAULT_INPUT_DATA
    out_dir: Path | None = None
    golden_output: Path = DEFAULT_GOLDEN_OUTPUT
    scaffold_path: Path = DEFAULT_SCAFFOLD_PATH
    memory_store_path: Path = DEFAULT_MEMORY_STORE
    # Which paragraph attribution.py treats as "the reference implementation
    # to hold constant while attributing a divergence to the unit under
    # test" (N1), and where its known-correct body lives. Interest-specific
    # defaults preserve every pre-existing call site; a second program
    # (Step S1/S2's FEECALC) overrides both -- see cli.py's PROGRAM_SPECS.
    reference_body_path: Path = DEFAULT_REFERENCE_BODY_PATH
    reference_paragraph_id: str = DEFAULT_REFERENCE_PARAGRAPH_ID
    # Field/accessor/signature tables that build_context/build_synthesis_prompt/
    # synthesize_paragraph derive their per-program content from (Step S1
    # generalization) -- interest.cob's INTEREST_SPEC by default, overridden
    # per program via cli.py's PROGRAM_PROFILES.
    scaffold_spec: ScaffoldSpec = field(default_factory=lambda: INTEREST_SPEC)
    max_repairs: int = DEFAULT_MAX_REPAIRS
    model: str = DEFAULT_MODEL
    seed: int = DEFAULT_SEED
    replay: bool = False
    # BACKEND_PLAN.md SS4.2's "candidate path or synthesis mode": when set,
    # Orchestrator uses this file's contents as the method body for the
    # program's one synthesis unit instead of calling synthesize_paragraph
    # -- zero model calls, straight to compile+verify (and, if it diverges,
    # the same repair loop a synthesized body would get). Not part of SRS
    # SS3.9.1's `weaver migrate` flag surface, so weaver/cli.py never sets
    # it; only the backend exposes it (CreateRunRequest.candidate_path /
    # synthesis_mode). None (the default) means synthesis mode, unchanged
    # from before this field existed. Added 2026-08-12.
    candidate_body_path: Path | None = None

    @classmethod
    def default(cls) -> RunSpec:
        return cls()

    def replace(self, **changes: object) -> RunSpec:
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, str | int | bool | None]:
        """Serialised form written to a run directory's params.json
        (the NFR-D1 reproducibility record)."""
        out: dict[str, str | int | bool | None] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Path):
                out[f.name] = str(value)
            elif isinstance(value, ScaffoldSpec):
                out[f.name] = value.paragraph_id
            else:
                out[f.name] = value
        return out
