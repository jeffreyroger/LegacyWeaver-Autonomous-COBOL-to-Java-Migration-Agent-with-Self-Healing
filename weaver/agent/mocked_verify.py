"""Real parity verification over a mocked subprogram -- Phase Z1
(migration-framework-spec.md Section 2.1's Dynamic Mocking, Section 2.2's
three-axis Parity Gate). Sibling to `weaver/agent/subprogram_verify.py`
(Phase X3), reusing its real driver-compilation machinery rather than
duplicating it: same `cobc`/WSL-delegation posture (CLAUDE.md rule 10's
Phase X3 exception), same real oracle-vs-candidate comparison discipline
(Non-Negotiable Design Decision 3 -- oracle output always comes from a
real, currently-compiled run, never fabricated).

The oracle side compiles a REWRITTEN copy of the subprogram's source
(`weaver/agent/mock_generator.py` -- every `EXEC SQL`/`EXEC CICS` block
replaced by its deterministic mock, since neither a database nor a CICS
region exists to call for real here); the candidate side's Java body is
expected to call the matching `WeaverMockRuntime.call(signature)` for each
mocked value. Both sides' stdout, interleaved with their `PARA:`/`STUB:`
trace lines and final formatted output line, feeds all three parity axes:
Terminal State (byte-for-byte, reusing `subprogram_verify._to_raw`/`_from_raw`),
Paragraphs Hit, and External Stub Log (`weaver/agent/parity_axes.py`).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from weaver.agent import parity_axes
from weaver.agent.mock_generator import MockMap, default_mock_map, rewrite_cobol_source
from weaver.agent.parity_axes import ParagraphsHitDivergence, StubLogDivergence
from weaver.agent.subprogram_verify import (
    TIMEOUT_SECONDS, _cobol_driver_source, _from_raw, _raw_width, _run, _to_raw, _via_wsl,
)
from weaver.cobol.mock_directives import find_mock_directives


@dataclass(frozen=True)
class MockedVerifyResult:
    compiled: bool
    compile_error: str | None = None
    terminal_state_match: bool = False
    oracle_output: object = None
    candidate_output: object = None
    paragraphs_hit_divergence: ParagraphsHitDivergence | None = None
    stub_log_divergence: StubLogDivergence | None = None
    oracle_trace: tuple[str, ...] = field(default_factory=tuple)
    candidate_trace: tuple[str, ...] = field(default_factory=tuple)

    @property
    def all_axes_match(self) -> bool:
        return self.compiled and self.terminal_state_match \
            and self.paragraphs_hit_divergence is None and self.stub_log_divergence is None


def _java_runtime_source(mock_map: MockMap) -> str:
    entries = ",\n".join(
        f'            Map.entry("{signature}", "{value.literal}")' for signature, value in mock_map.items()
    )
    return f"""\
import java.util.Map;

public final class WeaverMockRuntime {{
    private static final Map<String, String> VALUES = Map.ofEntries(
{entries}
    );

    public static java.math.BigDecimal call(String signature) {{
        System.out.println("STUB:" + signature);
        String literal = VALUES.get(signature);
        if (literal == null) {{
            throw new IllegalArgumentException("no mock value for signature: " + signature);
        }}
        return new java.math.BigDecimal(literal);
    }}

    public static void trace(String paragraphName) {{
        System.out.println("PARA:" + paragraphName);
    }}
}}
"""


def verify_mocked_subprogram(model, candidate_method_body: str, witness, work_dir: Path,
                              mock_map: MockMap | None = None) -> MockedVerifyResult:
    """`witness` is the single input value (this Phase's fixture is the
    N=1 back-compat shape). `candidate_method_body` is expected to call
    `WeaverMockRuntime.call("<signature>")` for each mocked directive the
    paragraph's real body contains."""
    # Parsed from the FULL source, not model.paragraph_source: Statement
    # line numbers are relative to whatever text they were parsed from,
    # and rewrite_cobol_source below splices by those same line numbers
    # into full_source -- both must agree on line numbering.
    full_source = model.source_path.read_text(encoding="utf-8")
    directives = find_mock_directives(full_source)
    mock_map = mock_map if mock_map is not None else default_mock_map(directives)

    via_wsl = _via_wsl()
    oracle_dir = work_dir / "oracle"
    candidate_dir = work_dir / "candidate"

    # --- oracle: compile the REWRITTEN source, real cobc ---
    oracle_dir.mkdir(parents=True, exist_ok=True)
    rewritten = rewrite_cobol_source(full_source, directives, mock_map, paragraph_names=[model.paragraph_id])
    module_src = oracle_dir / model.source_path.name
    module_src.write_text(rewritten, encoding="utf-8")
    (oracle_dir / "driver.cob").write_text(_cobol_driver_source(model), encoding="utf-8")

    result = _run(["cobc", "-m", module_src.name, "-o", f"{model.program_id}.so"], oracle_dir, "", via_wsl=via_wsl)
    if result.returncode != 0:
        return MockedVerifyResult(compiled=False, compile_error=f"oracle cobc -m failed:\n{result.stdout}\n{result.stderr}")
    result = _run(["cobc", "-x", "driver.cob", "-o", "driver"], oracle_dir, "", via_wsl=via_wsl)
    if result.returncode != 0:
        return MockedVerifyResult(compiled=False, compile_error=f"oracle cobc -x failed:\n{result.stdout}\n{result.stderr}")

    # --- candidate: compile the mock runtime + candidate class + driver ---
    from weaver.agent.subprogram_scaffold import _class_name, generate as generate_scaffold

    candidate_dir.mkdir(parents=True, exist_ok=True)
    class_name = _class_name(model.program_id)
    trace_line = f'        WeaverMockRuntime.trace("{model.paragraph_id}");'
    full_body = f"{trace_line}\n{candidate_method_body}"
    (candidate_dir / f"{class_name}.java").write_text(generate_scaffold(model, method_body=full_body), encoding="utf-8")
    (candidate_dir / "WeaverMockRuntime.java").write_text(_java_runtime_source(mock_map), encoding="utf-8")
    in_p, out_p = model.input_params[0], model.output_params[0]
    (candidate_dir / "Driver.java").write_text(
        f"""\
public final class Driver {{
    public static void main(String[] args) throws Exception {{
        java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(System.in));
        String line = br.readLine().trim();
        java.math.BigDecimal input = new java.math.BigDecimal(new java.math.BigInteger(line)).movePointLeft({in_p.decimal_scale});
        java.math.BigDecimal output = {class_name}.mainPara(input);
        java.math.BigDecimal scaled = output.movePointRight({out_p.decimal_scale}).setScale(0, java.math.RoundingMode.UNNECESSARY);
        System.out.println(String.format("%0{_raw_width(out_p)}d", scaled.longValueExact()));
    }}
}}
""",
        encoding="utf-8",
    )
    javac = subprocess.run(
        ["javac", "-d", ".", f"{class_name}.java", "WeaverMockRuntime.java", "Driver.java"],
        cwd=candidate_dir, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
    )
    if javac.returncode != 0:
        return MockedVerifyResult(compiled=False, compile_error=f"candidate javac failed:\n{javac.stdout}\n{javac.stderr}")

    # --- run both, real ---
    in_width, in_scale = _raw_width(in_p), in_p.decimal_scale
    out_scale = out_p.decimal_scale
    raw_in = _to_raw(witness, in_width, in_scale)

    oracle_proc = _run(["./driver"], oracle_dir, raw_in + "\n", via_wsl=via_wsl)
    oracle_stdout_lines = oracle_proc.stdout.splitlines()
    oracle_raw = oracle_stdout_lines[-1].strip() if oracle_stdout_lines else ""
    oracle_output = _from_raw(oracle_raw, out_scale) if oracle_raw else None

    candidate_proc = subprocess.run(
        ["java", "-cp", ".", "Driver"], cwd=candidate_dir, input=raw_in + "\n",
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
    )
    candidate_stdout_lines = candidate_proc.stdout.splitlines()
    candidate_raw = candidate_stdout_lines[-1].strip() if candidate_stdout_lines else ""
    candidate_output = _from_raw(candidate_raw, out_scale) if candidate_raw else None

    return MockedVerifyResult(
        compiled=True,
        terminal_state_match=(oracle_raw == candidate_raw),
        oracle_output=oracle_output,
        candidate_output=candidate_output,
        paragraphs_hit_divergence=parity_axes.compare_paragraphs_hit(oracle_stdout_lines, candidate_stdout_lines),
        stub_log_divergence=parity_axes.compare_stub_log(oracle_stdout_lines, candidate_stdout_lines),
        oracle_trace=tuple(oracle_stdout_lines),
        candidate_trace=tuple(candidate_stdout_lines),
    )


__all__ = ["MockedVerifyResult", "verify_mocked_subprogram"]
