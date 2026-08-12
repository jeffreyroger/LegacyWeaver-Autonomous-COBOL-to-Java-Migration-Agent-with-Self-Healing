      *****************************************************************
      * WHSEPROC.CBL — warehouse order-line totals (fits this repo's
      * Phase U frontend scope, weaver/cobol/frontend.py: exactly one
      * input file, one output file, one 01-level input record, exactly
      * two 01-levels on the output file (detail line then totals
      * line), and exactly two paragraphs -- one driver, one synthesis
      * unit. Trimmed down from a six-file, twenty-paragraph original
      * that used constructs (COMP-3, OCCURS tables, multiple files,
      * STRING) this frontend does not model (weaver/cobol/pic.py
      * explicitly rejects COMP/COMP-3; load_program() raises on
      * anything but one input/output file, one/two 01-levels, and a
      * driver-plus-one-unit paragraph shape).
      *
      * Rules:
      *   - priority "H" orders (OR-PREMIUM 88-level true) get a 10%
      *     discount; everything else gets none.
      *   - order total = (quantity * unit price) - discount, truncated
      *     (no ROUNDED clause -- COBOL's default truncates toward
      *     zero, unlike a naive Java translation).
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. WHSEPROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ORDER-FILE  ASSIGN TO "orders.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "whseproc.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ORDER-FILE.
       01  ORDER-RECORD.
           05  OR-ORDER-ID        PIC X(10).
           05  OR-PRODUCT-ID      PIC X(10).
           05  OR-QUANTITY        PIC 9(5).
           05  OR-UNIT-PRICE      PIC 9(5)V99.
           05  OR-PRIORITY        PIC X(1).
               88  OR-PREMIUM     VALUE "H".

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ORDER-ID        PIC X(10).
           05  RL-PRODUCT-ID      PIC X(10).
           05  RL-TOTAL           PIC -(7)9.99.
           05  RL-PRIORITY        PIC X(1).
       01  TOTALS-LINE.
      *    Shares REPORT-FILE's buffer with REPORT-LINE (two 01-levels
      *    under one FD implicitly redefine each other), so TL-LABEL is
      *    set explicitly in MAIN-PARA rather than via VALUE.
           05  TL-LABEL           PIC X(20).
           05  TL-TOTAL           PIC -(9)9.99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-DISCOUNT            PIC 9(5)V99.
       01  WS-ORDER-TOTAL         PIC S9(7)V99.
       01  WS-TOTAL-SALES         PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ORDER-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ ORDER-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM CALCULATE-ORDER
               END-READ
           END-PERFORM

           MOVE "TOTAL SALES:" TO TL-LABEL
           MOVE WS-TOTAL-SALES TO TL-TOTAL
           WRITE TOTALS-LINE

           CLOSE ORDER-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       CALCULATE-ORDER.
           IF OR-PREMIUM
               COMPUTE WS-DISCOUNT =
                   OR-QUANTITY * OR-UNIT-PRICE * 0.10
           ELSE
               MOVE ZERO TO WS-DISCOUNT
           END-IF

           COMPUTE WS-ORDER-TOTAL =
               (OR-QUANTITY * OR-UNIT-PRICE) - WS-DISCOUNT

           ADD WS-ORDER-TOTAL TO WS-TOTAL-SALES

           MOVE OR-ORDER-ID   TO RL-ORDER-ID
           MOVE OR-PRODUCT-ID TO RL-PRODUCT-ID
           MOVE WS-ORDER-TOTAL TO RL-TOTAL
           MOVE OR-PRIORITY   TO RL-PRIORITY
           WRITE REPORT-LINE.
