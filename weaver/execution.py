"""Dual execution of oracle and candidate (Step D2, FR-9).

Rules:
  - Each program runs in its own fresh temporary working directory; neither
    can observe or overwrite the other's artefacts.
  - The input file is COPIED into each directory, never regenerated.
  - Each execution is bounded by a 30s wall-clock timeout (NFR-6).
  - Absence of an expected output file is recorded as a divergence, not
    raised as a harness error (FR-9).

Scoped local WSL delegation exception (CLAUDE.md rule 10, extending the
2026-08-20 SUBPROGRAM_VERIFICATION_PLAN.md Phase X3 exception to the main
verify path): when no native `cobc`/oracle execution is possible on
Windows and `WEAVER_COBC_VIA_WSL=1` is set, `run_oracle` runs the
already-compiled oracle binary through `wsl -e bash -lc` instead of
invoking it directly, mirroring `weaver/agent/subprogram_verify.py`'s
existing `_run`/`_via_wsl` pattern. This changes nothing about what gets
verified -- the same compiled binary runs against the same copied input
file either way, only the shell wrapper differs. A machine with a native
oracle binary directly executable on Windows never touches this path
regardless of the env var.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 30


def _via_wsl() -> bool:
    return os.environ.get("WEAVER_COBC_VIA_WSL") == "1"


def _to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = str(resolved)[len(resolved.drive):].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


@dataclass
class ExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str
    output_lines: list[str] | None
    timed_out: bool


def _run_in_isolated_dir(command: list[str], work_dir: Path, input_path: Path,
                          output_filename: str, *, via_wsl: bool = False) -> ExecutionResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, work_dir / input_path.name)

    if via_wsl:
        wsl_dir = _to_wsl_path(work_dir)
        shell_cmd = " ".join(shlex.quote(a) for a in command)
        run_argv = ["wsl", "-e", "bash", "-lc", f"cd {shlex.quote(wsl_dir)} && {shell_cmd}"]
    else:
        run_argv = command

    try:
        proc = subprocess.run(
            run_argv,
            cwd=None if via_wsl else work_dir,
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
    via_wsl = _via_wsl()
    if via_wsl:
        work_dir.mkdir(parents=True, exist_ok=True)
        local_binary = work_dir / binary_path.name
        shutil.copy2(binary_path, local_binary)
        local_binary.chmod(0o755)
        command = [f"./{binary_path.name}"]
    else:
        command = [str(binary_path.resolve())]
    return _run_in_isolated_dir(command, work_dir, input_path, output_filename, via_wsl=via_wsl)


def run_candidate(main_class: str, classpath: Path, work_dir: Path, input_path: Path,
                   output_filename: str) -> ExecutionResult:
    return _run_in_isolated_dir(
        ["java", "-cp", str(classpath.resolve()), main_class], work_dir, input_path, output_filename
    )
