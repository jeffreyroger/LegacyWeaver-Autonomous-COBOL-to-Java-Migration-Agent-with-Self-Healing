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
    final String orderId;
    final String productId;
    final java.math.BigDecimal quantity;
    final java.math.BigDecimal unitPrice;
    final String priority;

    AccountRecord(String orderId, String productId, java.math.BigDecimal quantity, java.math.BigDecimal unitPrice, String priority) {
        this.orderId = orderId;
        this.productId = productId;
        this.quantity = quantity;
        this.unitPrice = unitPrice;
        this.priority = priority;
    }

    static AccountRecord decode(String line) {
        return new AccountRecord(
                line.substring(0, 10),
                line.substring(10, 20),
                Scaffold.decodeUnsigned(line.substring(20, 25), 0),
                Scaffold.decodeUnsigned(line.substring(25, 32), 2),
                line.substring(32, 33)
        );
    }



    boolean isPremium() { return priority.equals("H"); }
}

final class ReportLine {
    final String orderId;
    final String productId;
    final java.math.BigDecimal total;
    final String priority;

    ReportLine(String orderId, String productId, java.math.BigDecimal total, String priority) {
        this.orderId = orderId;
        this.productId = productId;
        this.total = total;
        this.priority = priority;
    }

    String encode() {
        return Scaffold.pad(orderId, 10) + Scaffold.pad(productId, 10) + CobolEdit.floatingSign(total, 11, 2) + Scaffold.pad(priority, 1);
    }
}

final class TotalsLine {
    final String label;
    final java.math.BigDecimal total;

    TotalsLine(String label, java.math.BigDecimal total) {
        this.label = label;
        this.total = total;
    }

    String encode() {
        return Scaffold.pad(label, 20) + CobolEdit.floatingSign(total, 13, 2);
    }
}

final class WorkingStorage {
    java.math.BigDecimal discount = java.math.BigDecimal.ZERO.setScale(2);
    java.math.BigDecimal orderTotal = java.math.BigDecimal.ZERO.setScale(2);
    java.math.BigDecimal totalSales = java.math.BigDecimal.ZERO.setScale(2);
}

public class Scaffold {
    private static final String INPUT_FILE = "orders.dat";
    private static final String OUTPUT_FILE = "whseproc.out";
    private static final int RECORD_WIDTH = 33;

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
            calculateOrder(ar, ws);
            ws.totalSales = ws.totalSales.add(ws.orderTotal);

            ReportLine rl = new ReportLine(ar.orderId, ar.productId, ws.orderTotal, ar.priority);
            // GnuCOBOL LINE SEQUENTIAL strips trailing spaces on WRITE.
            out.append(rstripSpaces(rl.encode())).append("\n");
        }

        TotalsLine tl = new TotalsLine(Scaffold.pad("TOTAL SALES:", 20), ws.totalSales);
        out.append(rstripSpaces(tl.encode())).append("\n");

        java.nio.file.Files.write(java.nio.file.Paths.get(OUTPUT_FILE),
            out.toString().getBytes(java.nio.charset.StandardCharsets.US_ASCII));
    }

    static void calculateOrder(AccountRecord ar, WorkingStorage ws) {
        // PARAGRAPH:CALCULATE-ORDER:BEGIN
if (ar.isPremium()) {
    ws.discount = ar.quantity.multiply(ar.unitPrice).multiply(new java.math.BigDecimal("0.10")).setScale(2, java.math.RoundingMode.DOWN);
} else {
    ws.discount = java.math.BigDecimal.ZERO.setScale(2);
}

ws.orderTotal = (ar.quantity.multiply(ar.unitPrice)).subtract(ws.discount).setScale(2, java.math.RoundingMode.DOWN);
        // PARAGRAPH:CALCULATE-ORDER:END
    }
}
