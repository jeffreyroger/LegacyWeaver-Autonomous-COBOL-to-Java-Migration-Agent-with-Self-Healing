"""Dual execution of oracle and candidate (Step D2, FR-9).

Rules:
  - Each program runs in its own fresh temporary working directory; neither
    can observe or overwrite the other's artefacts.
  - The input file is COPIED into each directory, never regenerated.
  - Each execution is bounded by a 30s wall-clock timeout (NFR-6).
  - Absence of an expected output file is recorded as a divergence, not
    raised as a harness error (FR-9).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 30


@dataclass
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    output_lines: list[str] | None
    timed_out: bool


def _run_in_isolated_dir(command: list[str], work_dir: Path, input_path: Path,
                          output_filename: str) -> ExecutionResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, work_dir / input_path.name)

    try:
        proc = subprocess.run(
            command,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        timed_out = False
        exit_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        exit_code = None
        stdout = e.stdout or ""
        stderr = e.stderr or ""

    output_path = work_dir / output_filename
    output_lines = output_path.read_text(encoding="utf-8").splitlines() if output_path.exists() else None

    return ExecutionResult(exit_code, stdout, stderr, output_lines, timed_out)


def run_oracle(binary_path: Path, work_dir: Path, input_path: Path,
               output_filename: str) -> ExecutionResult:
    return _run_in_isolated_dir([str(binary_path.resolve())], work_dir, input_path, output_filename)


def run_candidate(main_class: str, classpath: Path, work_dir: Path, input_path: Path,
                   output_filename: str) -> ExecutionResult:
    return _run_in_isolated_dir(
        ["java", "-cp", str(classpath.resolve()), main_class], work_dir, input_path, output_filename
    )
