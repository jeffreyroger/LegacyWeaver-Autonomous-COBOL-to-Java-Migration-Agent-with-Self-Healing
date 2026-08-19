"""Task 5 (FR-12.1-12.3): REDEFINES overlays as subclasses over a shared
byte[] buffer -- weaver/agent/scaffold.py's _redefines_subclasses /
_account_record_class.

Step 1 finding (see task-5-report.md for the verbatim grep output): none of
the five *_spec.py fixture files (compound/feecalc/shipcost/taxcalc/
tieraccum) declare a field with `redefines` set -- REDEFINES was parsed but
unexercised by scaffold generation for those five. INTEREST_SPEC is the
exception: its INPUT_LAYOUT (weaver/layout.py) already has AR-DORMANT and
AR-HOLD redefining AR-FLAGS, consumed today via the pre-existing flattened
`ar.dormant()`/`ar.hold()` substring-accessor style throughout the live
pipeline (report_ctor_map, condition_names, _main_class). Because of that,
the new subclass-generation branch is gated behind an explicit opt-in field,
`ScaffoldSpec.redefines_as_subclasses` (default False) -- it does not fire
merely because a field has `redefines` set, so INTEREST_SPEC's generated
output is completely unchanged by this task. TAXCALC_SPEC is used below as
the confirmed REDEFINES-free identity fixture.
"""

from weaver.agent.scaffold import ScaffoldSpec, ConditionName, WorkingStorageField, generate
from weaver.layout import Field


def test_no_redefines_produces_identical_output_to_before():
    # TAXCALC_SPEC has no redefines field anywhere in its layouts (Step 1),
    # so generate() must be byte-identical to the pre-Task-5 capture.
    from weaver.agent.taxcalc_spec import TAXCALC_SPEC

    output = generate(TAXCALC_SPEC)
    assert output == EXPECTED_UNCHANGED_OUTPUT


def test_interest_spec_output_unchanged_despite_having_redefines_fields():
    # INTEREST_SPEC's INPUT_LAYOUT DOES have redefines fields (AR-DORMANT,
    # AR-HOLD redefining AR-FLAGS) but redefines_as_subclasses defaults to
    # False, so it must keep taking the pre-Task-5 flattened-accessor path.
    from weaver.agent.scaffold import INTEREST_SPEC

    assert INTEREST_SPEC.redefines_as_subclasses is False
    output = generate(INTEREST_SPEC)
    assert "String dormant() { return flags.substring(0, 1); }" in output
    assert "String hold() { return flags.substring(1, 2); }" in output
    assert "extends AccountRecord" not in output


def test_redefines_produces_subclass_per_overlay():
    # Minimal synthetic ScaffoldSpec: AR-FLAGS (2 bytes) redefined by two
    # 1-byte elementary fields, AR-DORMANT and AR-HOLD -- the same shape as
    # INTEREST_SPEC's real overlay, but with the opt-in flag turned on. A
    # second overlay group, AR-EXTRA (3 numeric bytes) redefined by AR-SCORE
    # (a numeric field), exercises the CobolEdit.zeroPadded packing branch
    # (scaffold.py's `if f.numeric:` inside _redefines_subclasses), which the
    # AR-DORMANT/AR-HOLD group alone never reaches because both are String
    # fields.
    layout = (
        Field("AR-ID", offset=0, width=10, numeric=False),
        Field("AR-FLAGS", offset=10, width=2, numeric=False),
        Field("AR-DORMANT", offset=10, width=1, numeric=False, redefines="AR-FLAGS"),
        Field("AR-HOLD", offset=11, width=1, numeric=False, redefines="AR-FLAGS"),
        Field("AR-EXTRA", offset=12, width=3, numeric=False),
        Field("AR-SCORE", offset=12, width=3, numeric=True, decimal_scale=0, redefines="AR-EXTRA"),
    )
    spec = ScaffoldSpec(
        input_file="x.dat",
        output_file="y.out",
        input_layout=layout,
        report_layout=layout,
        totals_layout=layout,
        condition_names=(ConditionName("isDormant", "AR-DORMANT", "Y"),),
        paragraph_id="PROCESS-RECORD",
        paragraph_method="processRecord",
        ws_fields=(WorkingStorageField("total", 2),),
        accumulator_field="total",
        per_record_field="total",
        report_ctor_map={"AR-ID": "ar.id", "AR-FLAGS": "ar.flags", "AR-EXTRA": "ar.extra"},
        totals_ctor_map={"AR-ID": "ar.id", "AR-FLAGS": "ar.flags", "AR-EXTRA": "ar.extra"},
        redefines_as_subclasses=True,
    )
    output = generate(spec)
    assert "extends AccountRecord" in output
    assert output.count("getBytes()") >= 2
    assert output.count("setBytes(") >= 2
    assert "class FlagsOverlay extends AccountRecord" in output
    assert "final String dormant;" in output
    assert "final String hold;" in output

    # --- Correctness of decode, tied to AR-DORMANT's declared offset/width
    # (offset=10, width=1) -- a String (non-numeric) overlay field. This is
    # the exact literal substring expression _decode_field_expr must produce
    # for that offset/width; an off-by-one in _redefines_subclasses would
    # change this text.
    assert "this.dormant = line.substring(10, 11);" in output
    assert "this.hold = line.substring(11, 12);" in output

    # --- Correctness of pack (setBytes), tied to the same offset/width, for
    # the same non-numeric field -- Scaffold.pad + arraycopy positioned at
    # the field's declared offset within the shared buffer.
    assert (
        "System.arraycopy(Scaffold.pad(dormant, 1)"
        ".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, b, 10, 1);"
        in output
    )
    assert (
        "System.arraycopy(Scaffold.pad(hold, 1)"
        ".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, b, 11, 1);"
        in output
    )

    # --- Numeric overlay field (AR-SCORE, offset=12, width=3, scale=0):
    # covers the CobolEdit.zeroPadded packing branch, previously untested.
    assert "class ExtraOverlay extends AccountRecord" in output
    assert "final java.math.BigDecimal score;" in output
    assert "this.score = Scaffold.decodeUnsigned(line.substring(12, 15), 0);" in output
    assert (
        "System.arraycopy(CobolEdit.zeroPadded(score, 3)"
        ".getBytes(java.nio.charset.StandardCharsets.US_ASCII), 0, b, 12, 3);"
        in output
    )


# Golden text captured by running generate(TAXCALC_SPEC) BEFORE this task's
# code change (weaver/agent/scaffold.py, pre-Task-5).
EXPECTED_UNCHANGED_OUTPUT = '''/*
 * Scaffold.java — GENERATED, do not hand-edit (Step K2).
 *
 * Produced deterministically by weaver/agent/scaffold.py from a
 * ScaffoldSpec's field tables. Everything here is control flow, decoding,
 * and encoding implied by the declared byte offsets and edit masks — no
 * paragraph business logic. The one paragraph body that requires
 * interpretation is a stub between substitution markers;
 * weaver/agent/assemble.py replaces it with a synthesized or hand-written
 * body without touching anything else in this file.
 */

final class CobolEdit {
    private CobolEdit() {}

    /** Encode value as a COBOL PIC -(n)9.99-style floating-sign field. */
    static String floatingSign(java.math.BigDecimal value, int width, int scale) {
        int intCapacity = width - 1 - scale;
        boolean negative = value.signum() < 0;
        java.math.BigDecimal abs = value.abs().setScale(scale, java.math.RoundingMode.UNNECESSARY);
        String digits = abs.unscaledValue().toString();
        int totalDigits = intCapacity + scale;
        while (digits.length() < totalDigits) {
            digits = "0" + digits;
        }
        String intDigits = digits.substring(0, intCapacity);
        String fracDigits = digits.substring(intCapacity);

        int firstSig = intCapacity - 1;
        for (int i = 0; i < intCapacity - 1; i++) {
            if (intDigits.charAt(i) != '0') {
                firstSig = i;
                break;
            }
        }

        char[] out = new char[intCapacity];
        java.util.Arrays.fill(out, ' ');
        for (int i = firstSig; i < intCapacity; i++) {
            out[i] = intDigits.charAt(i);
        }
        if (firstSig > 0) {
            out[firstSig - 1] = negative ? '-' : ' ';
        }

        return new String(out) + "." + fracDigits;
    }

    /** Encode value as a COBOL PIC 9(n)-style plain zero-padded unsigned
     * field -- no sign column, no decimal point. Added 2026-08-12 to close
     * the gap tieraccum_layout.py originally worked around by dropping the
     * field instead (floatingSign always reserved a sign byte and always
     * emitted a decimal point, neither of which a plain PIC 9(n) has). */
    static String zeroPadded(java.math.BigDecimal value, int width) {
        String digits = value.setScale(0, java.math.RoundingMode.UNNECESSARY).toBigInteger().toString();
        while (digits.length() < width) {
            digits = "0" + digits;
        }
        return digits;
    }
}

final class AccountRecord {
    final String id;
    final java.math.BigDecimal income;
    final String bracket;
    final String active;

    AccountRecord(String id, java.math.BigDecimal income, String bracket, String active) {
        this.id = id;
        this.income = income;
        this.bracket = bracket;
        this.active = active;
    }

    static AccountRecord decode(String line) {
        return new AccountRecord(
                line.substring(0, 16),
                Scaffold.decodeSignedTrailing(line.substring(16, 27), line.charAt(27), 2),
                line.substring(28, 29),
                line.substring(29, 30)
        );
    }




}

final class ReportLine {
    final String id;
    final java.math.BigDecimal income;
    final java.math.BigDecimal tax;

    ReportLine(String id, java.math.BigDecimal income, java.math.BigDecimal tax) {
        this.id = id;
        this.income = income;
        this.tax = tax;
    }

    String encode() {
        return Scaffold.pad(id, 16) + CobolEdit.floatingSign(income, 13, 2) + CobolEdit.floatingSign(tax, 11, 2);
    }
}

final class TotalsLine {
    final String label;
    final java.math.BigDecimal total;
    final String filler;

    TotalsLine(String label, java.math.BigDecimal total, String filler) {
        this.label = label;
        this.total = total;
        this.filler = filler;
    }

    String encode() {
        return Scaffold.pad(label, 30) + CobolEdit.floatingSign(total, 11, 2) + Scaffold.pad(filler, 1);
    }
}

final class WorkingStorage {
    java.math.BigDecimal tax = java.math.BigDecimal.ZERO.setScale(2);
    java.math.BigDecimal totalTax = java.math.BigDecimal.ZERO.setScale(2);
}

public class Scaffold {
    private static final String INPUT_FILE = "tax.dat";
    private static final String OUTPUT_FILE = "tax.out";
    private static final int RECORD_WIDTH = 30;

    static java.math.BigDecimal decodeUnsigned(String digits, int scale) {
        java.math.BigDecimal unscaled = new java.math.BigDecimal(new java.math.BigInteger(digits));
        return unscaled.movePointLeft(scale);
    }

    static java.math.BigDecimal decodeSignedTrailing(String digits, char sign, int scale) {
        java.math.BigDecimal unscaled = new java.math.BigDecimal(new java.math.BigInteger(digits));
        java.math.BigDecimal value = unscaled.movePointLeft(scale);
        return sign == '-' ? value.negate() : value;
    }

    static String pad(String s, int width) {
        return String.format("%-" + width + "s", s);
    }

    static String rstripSpaces(String s) {
        int end = s.length();
        while (end > 0 && s.charAt(end - 1) == ' ') {
            end--;
        }
        return s.substring(0, end);
    }

    public static void main(String[] args) throws java.io.IOException {
        java.util.List<String> lines = java.nio.file.Files.readAllLines(
            java.nio.file.Paths.get(INPUT_FILE), java.nio.charset.StandardCharsets.US_ASCII);

        StringBuilder out = new StringBuilder();
        WorkingStorage ws = new WorkingStorage();

        for (String rawLine : lines) {
            if (rawLine.isEmpty()) {
                continue;
            }
            String line = String.format("%-" + RECORD_WIDTH + "s", rawLine);
            AccountRecord ar = AccountRecord.decode(line);
            computeTax(ar, ws);
            ws.totalTax = ws.totalTax.add(ws.tax);

            ReportLine rl = new ReportLine(ar.id, ar.income, ws.tax);
            // GnuCOBOL LINE SEQUENTIAL strips trailing spaces on WRITE.
            out.append(rstripSpaces(rl.encode())).append("\\n");
        }

        TotalsLine tl = new TotalsLine(Scaffold.pad("TOTAL TAX:", 30), ws.totalTax, " ");
        out.append(rstripSpaces(tl.encode())).append("\\n");

        java.nio.file.Files.write(java.nio.file.Paths.get(OUTPUT_FILE),
            out.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII));
    }

    static void computeTax(AccountRecord ar, WorkingStorage ws) {
        // PARAGRAPH:COMPUTE-TAX:BEGIN
        throw new UnsupportedOperationException("COMPUTE-TAX not yet synthesized");
        // PARAGRAPH:COMPUTE-TAX:END
    }
}
'''
