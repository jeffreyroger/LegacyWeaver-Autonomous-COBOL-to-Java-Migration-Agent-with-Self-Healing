      *****************************************************************
      * BILLFEE.CBL -- Phase AA2 fixture (migration-framework-spec.md
      * Section 3.2, Class Designer dedup).
      *
      * Deliberately COPYs the SAME FEE-REC.cpy copybook fixtures/cobol_feecalc
      * already uses, so BILLFEE's input record layout is byte-for-byte
      * identical to FEECALC's -- a real-world "two independently-written
      * programs share a copybook" scenario, not a hand-crafted coincidence.
      * Its REPORT-FILE layout and business logic (a flat late-fee rule
      * keyed on FR-ACTIVE, not FEECALC's tiered rate) are deliberately
      * different, so only the INPUT layout is dedup-eligible -- a targeted,
      * not whole-file, case for weaver/agent/class_designer.py to find.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BILLFEE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT FEE-FILE ASSIGN TO "fees.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "bill.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  FEE-FILE.
           COPY "FEE-REC.cpy".

       FD  REPORT-FILE.
       01  BILL-REPORT-LINE.
           05  BR-ID              PIC X(16).
           05  BR-ACTIVE          PIC X(1).
           05  BR-LATE-FEE        PIC -(7)9.99.
       01  BILL-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-LATE-FEE            PIC S9(7)V99.
       01  WS-TOTAL-LATE-FEE      PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT FEE-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ FEE-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-LATE-FEE
               END-READ
           END-PERFORM

           MOVE "TOTAL LATE FEE:" TO TL-LABEL
           MOVE WS-TOTAL-LATE-FEE TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE BILL-TOTALS-LINE

           CLOSE FEE-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-LATE-FEE.
           IF FR-ACTIVE = 'Y'
               MOVE 0 TO WS-LATE-FEE
           ELSE
               COMPUTE WS-LATE-FEE = FR-BALANCE * 0.02500
           END-IF

           ADD WS-LATE-FEE TO WS-TOTAL-LATE-FEE

           MOVE FR-ID       TO BR-ID
           MOVE FR-ACTIVE   TO BR-ACTIVE
           MOVE WS-LATE-FEE TO BR-LATE-FEE
           WRITE BILL-REPORT-LINE.
