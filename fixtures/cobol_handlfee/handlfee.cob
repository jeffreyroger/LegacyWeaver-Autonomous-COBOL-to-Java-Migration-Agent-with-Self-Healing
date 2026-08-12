      *****************************************************************
      * HANDLFEE.CBL — warehouse handling-fee calculation.
      *
      * Same compound-condition EVALUATE TRUE shape as shipcost.cob
      * (WHEN clauses each test two fields together), new to the repo:
      * fee scales with HR-WEIGHT and HR-PRIORITY rather than weight
      * and zone. Truncates toward zero (no ROUNDED, T1); no signed or
      * trailing-separate field, matching the single-shape class this
      * program belongs to.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HANDLFEE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT HANDL-FILE ASSIGN TO "handlfee.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "handlfee.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  HANDL-FILE.
           COPY "HANDL-REC.cpy".

       FD  REPORT-FILE.
       01  HANDL-REPORT-LINE.
           05  EL-ID              PIC X(16).
           05  EL-WEIGHT          PIC -(5)9.99.
           05  EL-FEE             PIC -(5)9.99.
       01  HANDL-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-FEE                 PIC S9(5)V99.
       01  WS-TOTAL-FEE           PIC S9(7)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT HANDL-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ HANDL-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-HANDLFEE
               END-READ
           END-PERFORM

           MOVE "TOTAL FEE:" TO TL-LABEL
           MOVE WS-TOTAL-FEE TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE HANDL-TOTALS-LINE

           CLOSE HANDL-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-HANDLFEE.
           EVALUATE TRUE
               WHEN HR-WEIGHT > 50.00 AND HR-PRIORITY = 'H'
                   COMPUTE WS-FEE = HR-WEIGHT * 0.60
               WHEN HR-WEIGHT > 50.00 AND HR-PRIORITY = 'L'
                   COMPUTE WS-FEE = HR-WEIGHT * 0.40
               WHEN HR-WEIGHT NOT > 50.00 AND HR-PRIORITY = 'H'
                   COMPUTE WS-FEE = HR-WEIGHT * 0.35
               WHEN OTHER
                   COMPUTE WS-FEE = HR-WEIGHT * 0.20
           END-EVALUATE

           ADD WS-FEE TO WS-TOTAL-FEE

           MOVE HR-ID TO EL-ID
           MOVE HR-WEIGHT TO EL-WEIGHT
           MOVE WS-FEE TO EL-FEE
           WRITE HANDL-REPORT-LINE.
