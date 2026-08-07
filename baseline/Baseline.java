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
 *      exact decimal arithmetic.                                  (T1, T2)
 *   2. Interest rounded half-up to two decimals, where COBOL truncates
 *      toward zero.                                                   (T1)
 *   3. The 4-byte flag group is compared as a whole string against "Y",
 *      never through the REDEFINES overlay, so dormant accounts
 *      incorrectly accrue interest.                                   (T3)
 *   4. Output numbers are formatted with a general-purpose numeric
 *      formatter instead of the COBOL edit mask.                      (T5)
 *   5. The trailing separate sign character is parsed naively (or
 *      ignored), rather than decoded as a COBOL SIGN IS TRAILING
 *      SEPARATE field.                                                (T6)
 *
 * TODO(Step C3): implement per the Step C2 specification in
 * docs/specs/MVP_IMPLEMENTATION_PLAN.md. Must produce 201 output lines
 * (200 detail + 1 totals) and must NOT match the golden output.
 */

import java.io.*;
import java.nio.file.*;
import java.util.*;

public class Baseline {

    public static void main(String[] args) throws IOException {
        // TODO: read accounts.dat, slice fields by the (not-yet-ported)
        // input layout, compute interest with double + Math.round (T1),
        // compare AR-FLAGS as a raw 4-char string against "Y" (T3),
        // format output with String.format rather than an edit mask (T5).
        throw new UnsupportedOperationException("Baseline not yet implemented (Step C3)");
    }
}
