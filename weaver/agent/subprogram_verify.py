"""Real subprogram parity verification — Phase X3
(docs/specs/SUBPROGRAM_VERIFICATION_PLAN.md, blocking gate).

A subprogram produces no file to diff, so this is a new axis: for each
witness input, run the REAL `cobc`-compiled subprogram (via a small,
deterministically-generated COBOL driver) and the candidate Java method
(via a small, deterministically-generated Java driver) against the same
input, and compare their outputs byte-for-byte -- same comparison
contract as the rest of the harness (CLAUDE.md rule 3; Non-Negotiable
Design Decision 2), never a second equivalence rule.

No witness output is ever fabricated (Non-Negotiable Design Decision 3):
the oracle side always runs the real, currently-compiled subprogram
source at `model.source_path`.

**Local WSL delegation (Non-Negotiable Design Decision 5, disclosed, not a
default-path change).** This dev environment has no native `cobc`;
`WEAVER_COBC_VIA_WSL=1` in the environment routes GnuCOBOL invocations
through `wsl -e bash -lc`, exactly mirroring CLAUDE.md rule 10's existing
Groq/Text-Refinement exceptions in spirit -- opt-in only, never read
anywhere else, and never the default when a native `cobc` is present (CI's
native Linux runners never need it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

TIMEOUT_SECONDS = 30
_DECIMAL_POINT_WIDTH = 0  # raw digit encoding carries no literal '.' character


@dataclass(frozen=True)
class SubprogramDivergence:
    witness_input: Decimal
    oracle_output: Decimal | None
    candidate_output: Decimal | None


@dataclass(frozen=True)
class SubprogramVerifyResult:
    compiled: bool
    divergences: tuple[SubprogramDivergence, ...] = field(default_factory=tuple)
    compile_error: str | None = None

    @property
    def divergence_count(self) -> int:
        return len(self.divergences)


def _via_wsl() -> bool:
    return shutil.which("cobc") is None and os.environ.get("WEAVER_COBC_VIA_WSL") == "1"


def _to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    rest = str(resolved)[len(resolved.drive):].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def _raw_width(field) -> int:
    return field.width  # PIC 9(n)V9(m) -- n+m raw digit positions, no '.' character


def _to_raw(value: Decimal, width: int, scale: int) -> str:
    scaled = int((value * (10 ** scale)).to_integral_exact())
    if scaled < 0 or scaled >= 10 ** width:
        raise ValueError(f"{value} does not fit PIC 9({width - scale})V9({scale})")
    return f"{scaled:0{width}d}"


def _from_raw(raw: str, scale: int) -> Decimal:
    return Decimal(int(raw)) / (10 ** scale)


def _cobol_driver_source(model) -> str:
    in_w, in_s = _raw_width(model.input_param), model.input_param.decimal_scale
    out_w, out_s = _raw_width(model.output_param), model.output_param.decimal_scale
    return f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DRIVER.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INPUT-RAW                PIC 9({in_w}).
       01  WS-INPUT REDEFINES WS-INPUT-RAW  PIC 9({in_w - in_s})V9({in_s}).
       01  WS-OUTPUT-RAW               PIC 9({out_w}).
       01  WS-OUTPUT REDEFINES WS-OUTPUT-RAW PIC 9({out_w - out_s})V9({out_s}).

       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-INPUT-RAW
           CALL "{model.program_id}" USING WS-INPUT WS-OUTPUT
           DISPLAY WS-OUTPUT-RAW
           STOP RUN.
"""


def _java_driver_source(class_name: str, in_scale: int, out_width: int, out_scale: int) -> str:
    return f"""\
public final class Driver {{
    public static void main(String[] args) throws Exception {{
        java.io.BufferedReader br = new java.io.BufferedReader(
            new java.io.InputStreamReader(System.in));
        String line = br.readLine().trim();
        java.math.BigDecimal input = new java.math.BigDecimal(new java.math.BigInteger(line))
            .movePointLeft({in_scale});
        java.math.BigDecimal output = {class_name}.mainPara(input);
        java.math.BigDecimal scaled = output.movePointRight({out_scale}).setScale(0, java.math.RoundingMode.UNNECESSARY);
        System.out.println(String.format("%0{out_width}d", scaled.longValueExact()));
    }}
}}
"""


def _run(argv: list[str], work_dir: Path, stdin_text: str, *, via_wsl: bool) -> subprocess.CompletedProcess:
    if via_wsl:
        import shlex

        wsl_dir = _to_wsl_path(work_dir)
        shell_cmd = " ".join(shlex.quote(a) for a in argv)
        full = ["wsl", "-e", "bash", "-lc", f"cd {shlex.quote(wsl_dir)} && {shell_cmd}"]
        return subprocess.run(full, input=stdin_text, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    env = dict(os.environ)
    env["COB_LIBRARY_PATH"] = "."
    return subprocess.run(argv, cwd=work_dir, input=stdin_text, capture_output=True, text=True,
                           timeout=TIMEOUT_SECONDS, env=env)


def _compile_oracle_driver(model, work_dir: Path, *, via_wsl: bool) -> str | None:
    """Compiles the REAL subprogram source at model.source_path plus a
    generated driver, real cobc only. Returns an error string, or None."""
    work_dir.mkdir(parents=True, exist_ok=True)
    module_src = work_dir / model.source_path.name
    module_src.write_text(model.source_path.read_text(encoding="utf-8"), encoding="utf-8")
    (work_dir / "driver.cob").write_text(_cobol_driver_source(model), encoding="utf-8")

    result = _run(["cobc", "-m", module_src.name, "-o", f"{model.program_id}.so"], work_dir, "", via_wsl=via_wsl)
    if result.returncode != 0:
        return f"cobc -m failed:\n{result.stdout}\n{result.stderr}"

    result = _run(["cobc", "-x", "driver.cob", "-o", "driver"], work_dir, "", via_wsl=via_wsl)
    if result.returncode != 0:
        return f"cobc -x failed:\n{result.stdout}\n{result.stderr}"
    return None


def _compile_candidate_driver(model, candidate_method_body: str, work_dir: Path) -> str | None:
    from weaver.agent.subprogram_scaffold import _class_name, generate as generate_scaffold

    work_dir.mkdir(parents=True, exist_ok=True)
    class_name = _class_name(model.program_id)
    scaffold_source = generate_scaffold(model, method_body=candidate_method_body)
    (work_dir / f"{class_name}.java").write_text(scaffold_source, encoding="utf-8")
    (work_dir / "Driver.java").write_text(
        _java_driver_source(class_name, model.input_param.decimal_scale,
                             _raw_width(model.output_param), model.output_param.decimal_scale),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["javac", "-d", ".", f"{class_name}.java", "Driver.java"],
        cwd=work_dir, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return f"javac failed:\n{result.stdout}\n{result.stderr}"
    return None


def verify_subprogram(model, candidate_method_body: str, witnesses: list[Decimal],
                       work_dir: Path) -> SubprogramVerifyResult:
    """Real byte-for-byte parity check over `witnesses` (Phase X3's
    blocking-gate axis). `work_dir` holds the compiled oracle driver +
    candidate Java driver; kept for post-mortem inspection like the rest
    of this repo's `generated/orchestrator/<unit>/...` convention."""
    via_wsl = _via_wsl()
    oracle_dir = work_dir / "oracle"
    candidate_dir = work_dir / "candidate"

    oracle_error = _compile_oracle_driver(model, oracle_dir, via_wsl=via_wsl)
    if oracle_error is not None:
        return SubprogramVerifyResult(compiled=False, compile_error=f"oracle: {oracle_error}")

    candidate_error = _compile_candidate_driver(model, candidate_method_body, candidate_dir)
    if candidate_error is not None:
        return SubprogramVerifyResult(compiled=False, compile_error=f"candidate: {candidate_error}")

    in_scale = model.input_param.decimal_scale
    in_width = _raw_width(model.input_param)
    out_scale = model.output_param.decimal_scale

    divergences: list[SubprogramDivergence] = []
    for witness in witnesses:
        raw_in = _to_raw(witness, in_width, in_scale)

        oracle_proc = _run(["./driver"], oracle_dir, raw_in + "\n", via_wsl=via_wsl)
        oracle_raw = oracle_proc.stdout.strip()
        oracle_out = _from_raw(oracle_raw, out_scale) if oracle_raw else None

        candidate_proc = subprocess.run(
            ["java", "-cp", ".", "Driver"], cwd=candidate_dir, input=raw_in + "\n",
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        candidate_raw = candidate_proc.stdout.strip()
        candidate_out = _from_raw(candidate_raw, out_scale) if candidate_raw else None

        if oracle_raw != candidate_raw:
            divergences.append(SubprogramDivergence(witness, oracle_out, candidate_out))

    return SubprogramVerifyResult(compiled=True, divergences=tuple(divergences))


def harvest_subprogram_fixtures(model, witnesses: list[Decimal], work_dir: Path):
    """Phase X5: run ONLY the real oracle side once per witness and return
    the resulting `UnitFixture`s -- GRAPH_PLAN.md M5's "harvest once"
    discipline, applied to a subprogram's call boundary instead of a
    paragraph's file-record boundary. Every fixture's output_state comes
    from a real, currently-compiled `cobc` run (Non-Negotiable Design
    Decision 3) -- never inferred from `verify_subprogram`'s candidate
    side.
    """
    from weaver.agent.trace_harvest import UnitFixture

    via_wsl = _via_wsl()
    oracle_dir = work_dir / "oracle"
    oracle_error = _compile_oracle_driver(model, oracle_dir, via_wsl=via_wsl)
    if oracle_error is not None:
        raise RuntimeError(f"harvest failed: oracle: {oracle_error}")

    in_scale = model.input_param.decimal_scale
    in_width = _raw_width(model.input_param)
    out_width = _raw_width(model.output_param)

    fixtures = []
    for index, witness in enumerate(witnesses):
        raw_in = _to_raw(witness, in_width, in_scale)
        oracle_proc = _run(["./driver"], oracle_dir, raw_in + "\n", via_wsl=via_wsl)
        oracle_raw = oracle_proc.stdout.strip()
        if len(oracle_raw) != out_width or not oracle_raw.isdigit():
            raise RuntimeError(
                f"harvest failed: oracle produced no valid output for witness {witness} "
                f"(stdout={oracle_proc.stdout!r} stderr={oracle_proc.stderr!r})"
            )
        fixtures.append(UnitFixture(
            paragraph_id=model.paragraph_id,
            record_index=index,
            input_state={model.input_param.name: raw_in},
            output_state={model.output_param.name: oracle_raw},
        ))
    return fixtures


def verify_subprogram_from_cache(model, candidate_method_body: str, cache, work_dir: Path
                                  ) -> SubprogramVerifyResult:
    """Phase X5 fast path: compiles and runs ONLY the candidate side,
    comparing against `cache`'s already-harvested real oracle outputs --
    never re-invoking `cobc`. Falls back to nothing itself (AC-17's
    posture, GRAPH_PLAN.md M8): the caller decides what to do on a cache
    miss/mismatch, this function only ever consumes a cache it was
    already handed."""
    candidate_dir = work_dir / "candidate"
    candidate_error = _compile_candidate_driver(model, candidate_method_body, candidate_dir)
    if candidate_error is not None:
        return SubprogramVerifyResult(compiled=False, compile_error=f"candidate: {candidate_error}")

    in_scale = model.input_param.decimal_scale
    out_scale = model.output_param.decimal_scale

    divergences: list[SubprogramDivergence] = []
    for fixture in cache.fixtures:
        raw_in = fixture.input_state[model.input_param.name]
        oracle_raw = fixture.output_state[model.output_param.name]
        witness = _from_raw(raw_in, in_scale)
        oracle_out = _from_raw(oracle_raw, out_scale)

        candidate_proc = subprocess.run(
            ["java", "-cp", ".", "Driver"], cwd=candidate_dir, input=raw_in + "\n",
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        candidate_raw = candidate_proc.stdout.strip()
        candidate_out = _from_raw(candidate_raw, out_scale) if candidate_raw else None

        if oracle_raw != candidate_raw:
            divergences.append(SubprogramDivergence(witness, oracle_out, candidate_out))

    return SubprogramVerifyResult(compiled=True, divergences=tuple(divergences))


__all__ = [
    "SubprogramDivergence", "SubprogramVerifyResult", "verify_subprogram",
    "harvest_subprogram_fixtures", "verify_subprogram_from_cache",
]
