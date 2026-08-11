/*
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
            out.append(rstripSpaces(rl.encode())).append("\n");
        }

        TotalsLine tl = new TotalsLine(Scaffold.pad("TOTAL TAX:", 30), ws.totalTax, " ");
        out.append(rstripSpaces(tl.encode())).append("\n");

        java.nio.file.Files.write(java.nio.file.Paths.get(OUTPUT_FILE),
            out.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII));
    }

    static void computeTax(AccountRecord ar, WorkingStorage ws) {
        // PARAGRAPH:COMPUTE-TAX:BEGIN
if (ar.income.compareTo(new java.math.BigDecimal("100000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.30")).setScale(2, java.math.RoundingMode.HALF_UP);
} else if (ar.income.compareTo(new java.math.BigDecimal("50000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.20")).setScale(2, java.math.RoundingMode.HALF_UP);
} else if (ar.income.compareTo(new java.math.BigDecimal("20000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.10")).setScale(2, java.math.RoundingMode.HALF_UP);
} else {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.05")).setScale(2, java.math.RoundingMode.HALF_UP);
}

        // PARAGRAPH:COMPUTE-TAX:END
    }
}
