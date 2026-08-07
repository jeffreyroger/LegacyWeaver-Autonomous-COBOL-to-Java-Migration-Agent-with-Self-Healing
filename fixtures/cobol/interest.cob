      *****************************************************************
      * INTEREST.CBL — the oracle (SRS FR-1, FR-2).
      *
      * Realistic financial batch computation over fixed-width sequential
      * records. Deliberately contains the six planted constructs that
      * unconstrained translation reliably mishandles (SRS FR-2):
      *
      *   T1 — arithmetic without explicit rounding (truncation)
      *   T2 — implied decimal position (PIC 9(n)V9(m))
      *   T3 — REDEFINES overlay on the flag group
      *   T4 — 88-level condition driving a tiered (premium) rate
      *   T5 — numeric edit mask with fixed width
      *   T6 — trailing separate sign
      *
      * TODO(Step B1/B2): complete DATA DIVISION per the hand-derived
      * offset table (39-byte record) and PROCEDURE DIVISION per the
      * stated interest rules (see MVP_IMPLEMENTATION_PLAN.md Step B5):
      *   - premium: rate * 1.15, TRUNCATED to 5 decimals, then applied
      *   - dormant: interest is always zero
      *   - otherwise: balance * rate / 365, TRUNCATED to 2 decimals
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTEREST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
      *    TODO: SELECT ACCOUNT-FILE ASSIGN TO "accounts.dat" ...
      *    TODO: SELECT REPORT-FILE  ASSIGN TO "interest.out" ...

       DATA DIVISION.
       FILE SECTION.
      *    TODO: FD ACCOUNT-FILE. COPY ACCOUNT-REC.
      *    TODO: FD REPORT-FILE.  01 REPORT-LINE PIC X(...).

       WORKING-STORAGE SECTION.
      *    TODO: working-storage fields, including the 88-level premium
      *    tier condition (T4) and the 5-decimal intermediate rate field
      *    whose narrowness causes the second truncation in Step B5.

       PROCEDURE DIVISION.
      *    TODO: read-compute-write loop; totals line; T1-T6 as above.
           STOP RUN.
