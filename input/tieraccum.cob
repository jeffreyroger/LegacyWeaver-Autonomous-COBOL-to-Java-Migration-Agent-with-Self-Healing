      *****************************************************************
      * TIERACCUM.CBL — Step U2's in-paragraph-loop program.
      *
      * ACCUMULATE-TIERS contains a PERFORM VARYING loop internal to the
      * paragraph itself, iterating UR-UNITS times per record -- every
      * other fixture's only loop lives in the scaffold's per-record
      * main loop (K2), never inside the synthesis unit. Tests whether
      * the "one paragraph's logic" framing (K1/M1) still holds when
      * that logic is itself iterative. Truncates toward zero at each
      * step (no ROUNDED, T1) and reads a SIGN TRAILING SEPARATE numeric
      * field (T6), same trap classes as every other fixture.
      *
      * Rule: for each of UR-UNITS sub-units (1..N), add
      * UR-BASE * 0.10 / unit-number, truncated, to a per-record
      * accumulator; the running report total is the sum of those
      * per-record accumulators.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TIERACCUM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TIER-FILE ASSIGN TO "tieraccum.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "tieraccum.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TIER-FILE.
           COPY "TIER-REC.cpy".

       FD  REPORT-FILE.
       01  TIER-REPORT-LINE.
           05  YL-ID              PIC X(16).
           05  YL-BASE            PIC -(9)9.99.
           05  YL-ACCUM           PIC -(7)9.99.
       01  TIER-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-IDX                 PIC 9(2).
       01  WS-STEP                PIC S9(7)V99.
       01  WS-ACCUM               PIC S9(7)V99.
       01  WS-TOTAL-ACCUM         PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TIER-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ TIER-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM ACCUMULATE-TIERS
               END-READ
           END-PERFORM

           MOVE "TOTAL ACCUM:" TO TL-LABEL
           MOVE WS-TOTAL-ACCUM TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE TIER-TOTALS-LINE

           CLOSE TIER-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       ACCUMULATE-TIERS.
           MOVE ZERO TO WS-ACCUM

           PERFORM VARYING WS-IDX FROM 1 BY 1 UNTIL WS-IDX > UR-UNITS
               COMPUTE WS-STEP = UR-BASE * 0.10 / WS-IDX
               ADD WS-STEP TO WS-ACCUM
           END-PERFORM

           ADD WS-ACCUM TO WS-TOTAL-ACCUM

           MOVE UR-ID       TO YL-ID
           MOVE UR-BASE     TO YL-BASE
           MOVE WS-ACCUM    TO YL-ACCUM
           WRITE TIER-REPORT-LINE.
