/*
 * Baseline.java — DELIBERATELY UNCONSTRAINED TRANSLATION (control arm).
 *
 * This program is NOT a good-faith attempt at a correct translation of
 * INTEREST.CBL. It exists as the control arm of a measurement (SRS FR-7,
 * FR-8): it represents what unconstrained/naive translation typically
 * produces, so that the divergence count against the oracle measures
 * something real rather than an invented strawman.
 *
 * Declared deviations from COBOL semantics (SRS FR-8):
 *   1. Monetary values parsed and computed using IEEE-754 double, not
 *      exact decimal arithmetic.
 *   2. Interest rounded half-up to two decimals (Math.round), where
 *      COBOL's default COMPUTE truncates toward zero.                 (T1)
 *   3. The trailing separate sign byte on AR-BALANCE is never read;
 *      balance is always parsed as non-negative. Negative-balance
 *      accounts therefore get their interest computed on the wrong
 *      (positive) magnitude.                                          (T6)
 *   4. The 4-byte flag group is compared as a whole string against "Y",
 *      never through the REDEFINES overlay, so this comparison is
 *      always false and dormant accounts incorrectly accrue interest.
 *      (The raw dormant character is still copied correctly to the
 *      output column -- only the interest-zeroing logic is wrong.)    (T3)
 *   5. Output numbers are formatted with Java's general-purpose
 *      String.format rather than replicating the COBOL edit mask; this
 *      coincidentally matches column width for in-range values but
 *      does not reserve headroom for a sign on a maximum-magnitude
 *      value the way the (corrected) COBOL picture does.              (T5)
 *
 * Implements Step C2 of docs/specs/MVP_IMPLEMENTATION_PLAN.md.
 */

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class Baseline {

    private static final String INPUT_FILE = "accounts.dat";
    private static final String OUTPUT_FILE = "interest.out";

    public static void main(String[] args) throws IOException {
        List<String> lines = Files.readAllLines(Paths.get(INPUT_FILE), StandardCharsets.US_ASCII);

        StringBuilder out = new StringBuilder();
        double totalInterest = 0.0;

        for (String line : lines) {
            if (line.isEmpty()) {
                continue;
            }

            String id = line.substring(0, 16);
            // Deviation 3: the sign byte (index 27) is never read.
            String balanceDigits = line.substring(16, 27);
            double balance = Long.parseLong(balanceDigits) / 100.0;

            String rateDigits = line.substring(28, 34);
            double rate = Long.parseLong(rateDigits) / 100000.0;

            char type = line.charAt(34);
            char dormantChar = line.charAt(35);

            // Deviation 4: whole-string comparison against a 4-byte field
            // can never be true.
            String flagsRaw = line.substring(35, 39);
            boolean treatedAsDormant = flagsRaw.equals("Y");

            double appliedRate = (type == 'P') ? rate * 1.15 : rate;

            double interest;
            if (treatedAsDormant) {
                interest = 0.0;
            } else {
                double raw = balance * appliedRate / 365.0;
                // Deviation 2: round half-up instead of truncate.
                interest = Math.round(raw * 100.0) / 100.0;
            }

            totalInterest += interest;

            out.append(String.format("%-16s%1s%13.2f%11.2f%1s\n",
                    id, type, balance, interest, dormantChar));
        }

        out.append(String.format("%-30s%11.2f \n", "TOTAL INTEREST:", totalInterest));

        Files.write(Paths.get(OUTPUT_FILE), out.toString().getBytes(StandardCharsets.US_ASCII));
    }
}
