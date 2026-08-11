      *****************************************************************
      * SHIPCOST.CBL — Step U4's compound-condition lookup program.
      *
      * COMPUTE-SHIPCOST uses EVALUATE TRUE with WHEN clauses that each
      * test a compound AND condition spanning two different fields
      * (SR-WEIGHT and SR-ZONE together) -- unlike feecalc.cob's flat
      * EVALUATE (switches on one field) or taxcalc.cob's nested
      * IF/ELSE ladder (thresholds one field). Still truncates toward
      * zero (no ROUNDED, T1); deliberately has no signed/trailing-
      * separate field, isolating the compound-condition shape as the
      * only new thing under test (Step U4).
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SHIPCOST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT SHIP-FILE ASSIGN TO "shipcost.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "shipcost.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  SHIP-FILE.
           COPY "SHIP-REC.cpy".

       FD  REPORT-FILE.
       01  SHIP-REPORT-LINE.
           05  EL-ID              PIC X(16).
           05  EL-WEIGHT          PIC -(5)9.99.
           05  EL-COST            PIC -(5)9.99.
       01  SHIP-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-COST                PIC S9(5)V99.
       01  WS-TOTAL-COST          PIC S9(7)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT SHIP-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ SHIP-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-SHIPCOST
               END-READ
           END-PERFORM

           MOVE "TOTAL COST:" TO TL-LABEL
           MOVE WS-TOTAL-COST TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE SHIP-TOTALS-LINE

           CLOSE SHIP-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-SHIPCOST.
           EVALUATE TRUE
               WHEN SR-WEIGHT > 100.00 AND SR-ZONE = 'A'
                   COMPUTE WS-COST = SR-WEIGHT * 0.50
               WHEN SR-WEIGHT > 100.00 AND SR-ZONE = 'B'
                   COMPUTE WS-COST = SR-WEIGHT * 0.75
               WHEN SR-WEIGHT NOT > 100.00 AND SR-ZONE = 'A'
                   COMPUTE WS-COST = SR-WEIGHT * 0.30
               WHEN OTHER
                   COMPUTE WS-COST = SR-WEIGHT * 0.45
           END-EVALUATE

           ADD WS-COST TO WS-TOTAL-COST

           MOVE SR-ID       TO EL-ID
           MOVE SR-WEIGHT   TO EL-WEIGHT
           MOVE WS-COST     TO EL-COST
           WRITE SHIP-REPORT-LINE.
