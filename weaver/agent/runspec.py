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
from dataclasses import dataclass
from pathlib import Path

# Defaults copied verbatim from SRS SS3.9.1.
DEFAULT_MAX_REPAIRS = 3
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_SEED = 42

DEFAULT_COBOL_SOURCE = Path("fixtures/cobol/interest.cob")
DEFAULT_INPUT_DATA = Path("fixtures/data/accounts.dat")
DEFAULT_GOLDEN_OUTPUT = Path("fixtures/data/expected/golden_interest.out")
DEFAULT_SCAFFOLD_PATH = Path("generated/Scaffold.java")
DEFAULT_MEMORY_STORE = Path("generated/failure_memory.json")


@dataclass(frozen=True)
class RunSpec:
    cobol_source: Path = DEFAULT_COBOL_SOURCE
    copybook_dir: Path | None = None
    input_data: Path = DEFAULT_INPUT_DATA
    out_dir: Path | None = None
    golden_output: Path = DEFAULT_GOLDEN_OUTPUT
    scaffold_path: Path = DEFAULT_SCAFFOLD_PATH
    memory_store_path: Path = DEFAULT_MEMORY_STORE
    max_repairs: int = DEFAULT_MAX_REPAIRS
    model: str = DEFAULT_MODEL
    seed: int = DEFAULT_SEED
    replay: bool = False

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
            out[f.name] = str(value) if isinstance(value, Path) else value
        return out
