"""Generate the Java source for a COBOL floating-sign numeric edit mask.

`-(n)9.99`-style pictures: `n` floating sign positions, one mandatory
integer digit, a decimal point, and `decimal_scale` fraction digits.
Integer capacity (total integer digits, mandatory + floating) is derived
from the field width alone: `width - 1 - decimal_scale`.

This is emitted once as a shared Java helper (`CobolEdit.floatingSign`) and
called from both `ReportLine.encode()` and `TotalsLine.encode()` — see
docs/specs/scaffold_spec.md §3.
"""

from __future__ import annotations

JAVA_SOURCE = """\
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
"""
