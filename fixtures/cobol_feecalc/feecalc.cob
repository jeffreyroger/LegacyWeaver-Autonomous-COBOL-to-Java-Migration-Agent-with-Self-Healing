      *****************************************************************
      * FEECALC.CBL — Step S1's second program.
      *
      * Roughly 80 lines, flat fee tiers, different arithmetic and field
      * names from interest.cob, but sharing its truncation-toward-zero
      * default (T1) and its trailing-separate sign encoding on the
      * balance field (T6) -- the two trap classes this fixture exists
      * to demonstrate transferring across programs via failure memory.
      *
      * Fee rules: fee = balance * tier-rate, TRUNCATED (no ROUNDED
      * clause). Tier rate is a flat lookup, not a continuous rate like
      * interest.cob's AR-RATE -- deliberately different arithmetic
      * shape (single MULTIPLY, no DIVIDE) so this is not a copy-paste
      * of interest.cob.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FEECALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FEE-FILE ASSIGN TO "fees.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "fee.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  FEE-FILE.
           COPY "FEE-REC.cpy".

       FD  REPORT-FILE.
       01  FEE-REPORT-LINE.
           05  FL-ID              PIC X(16).
           05  FL-TIER            PIC X(1).
           05  FL-BALANCE         PIC -(9)9.99.
           05  FL-FEE             PIC -(7)9.99.
       01  FEE-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-RATE                PIC 9V9(5).
       01  WS-FEE                 PIC S9(7)V99.
       01  WS-TOTAL-FEE           PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FEE-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ FEE-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-FEE
               END-READ
           END-PERFORM

           MOVE "TOTAL FEE:" TO TL-LABEL
           MOVE WS-TOTAL-FEE TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE FEE-TOTALS-LINE

           CLOSE FEE-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-FEE.
           EVALUATE FR-TIER
               WHEN 'A'
                   MOVE 0.01500 TO WS-RATE
               WHEN 'B'
                   MOVE 0.01000 TO WS-RATE
               WHEN OTHER
                   MOVE 0.00500 TO WS-RATE
           END-EVALUATE

           COMPUTE WS-FEE = FR-BALANCE * WS-RATE

           ADD WS-FEE TO WS-TOTAL-FEE

           MOVE FR-ID       TO FL-ID
           MOVE FR-TIER     TO FL-TIER
           MOVE FR-BALANCE  TO FL-BALANCE
           MOVE WS-FEE      TO FL-FEE
           WRITE FEE-REPORT-LINE.
