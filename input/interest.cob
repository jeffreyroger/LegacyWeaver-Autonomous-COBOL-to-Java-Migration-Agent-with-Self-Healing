      *****************************************************************
      * INTEREST.CBL — the oracle (SRS FR-1, FR-2).
      *
      * Realistic financial batch computation over fixed-width sequential
      * records. Deliberately contains the six planted constructs that
      * unconstrained translation reliably mishandles (SRS FR-2):
      *
      *   T1 — arithmetic without explicit rounding (default COMPUTE
      *        truncates; no ROUNDED clause is used anywhere below)
      *   T2 — implied decimal position (AR-BALANCE, AR-RATE: PIC 9(n)V9(m))
      *   T3 — REDEFINES overlay on the flag group (AR-FLAGS-R)
      *   T4 — 88-level condition driving a tiered (premium) rate
      *   T5 — numeric edit mask with fixed width (RL-BALANCE, RL-INTEREST)
      *   T6 — trailing separate sign (AR-BALANCE SIGN IS TRAILING SEPARATE)
      *
      * Interest rules (independently hand-verified, Step B5):
      *   - premium (AR-PREMIUM 88-level true): applied rate = AR-RATE *
      *     1.15, TRUNCATED to 5 decimals by the WS-APPLIED-RATE PIC
      *     clause (the field only holds 5 decimals, so the extra digit
      *     is discarded before it is ever used in the interest formula).
      *   - dormant (AR-IS-DORMANT true): interest is always zero,
      *     regardless of balance.
      *   - otherwise: interest = TRUNCATE(balance * applied-rate / 365,
      *     2 decimals). No ROUNDED clause; COBOL's default is
      *     truncation toward zero, not the round-half-up a naive Java
      *     translation typically applies.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTEREST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO "accounts.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "interest.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
           COPY "ACCOUNT-REC.cpy".

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ID              PIC X(16).
           05  RL-TYPE            PIC X(1).
           05  RL-BALANCE         PIC -(9)9.99.
           05  RL-INTEREST        PIC -(7)9.99.
           05  RL-DORMANT         PIC X(1).
       01  TOTALS-LINE.
      *    Note: TOTALS-LINE shares REPORT-FILE's buffer with
      *    REPORT-LINE (multiple 01-levels under one FD implicitly
      *    redefine each other), so VALUE clauses here would never take
      *    effect at runtime -- TL-LABEL is set explicitly in MAIN-PARA.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-APPLIED-RATE        PIC 9V9(5).
       01  WS-INTEREST            PIC S9(7)V99.
       01  WS-TOTAL-INTEREST      PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ ACCOUNT-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM PROCESS-RECORD
               END-READ
           END-PERFORM

           MOVE "TOTAL INTEREST:" TO TL-LABEL
           MOVE WS-TOTAL-INTEREST TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE TOTALS-LINE

           CLOSE ACCOUNT-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       PROCESS-RECORD.
           IF AR-PREMIUM
               COMPUTE WS-APPLIED-RATE = AR-RATE * 1.15
           ELSE
               MOVE AR-RATE TO WS-APPLIED-RATE
           END-IF

           IF AR-IS-DORMANT
               MOVE ZERO TO WS-INTEREST
           ELSE
               COMPUTE WS-INTEREST =
                   AR-BALANCE * WS-APPLIED-RATE / 365
           END-IF

           ADD WS-INTEREST TO WS-TOTAL-INTEREST

           MOVE AR-ID       TO RL-ID
           MOVE AR-TYPE     TO RL-TYPE
           MOVE AR-BALANCE  TO RL-BALANCE
           MOVE WS-INTEREST TO RL-INTEREST
           MOVE AR-DORMANT  TO RL-DORMANT
           WRITE REPORT-LINE.
      * touched to retrigger CI with debug error output
