      *****************************************************************
      * TAXCALC.CBL — Step U1's nested-conditional program.
      *
      * COMPUTE-TAX is a four-bracket progressive ladder of nested
      * IF/ELSE statements -- a different control-flow shape from
      * interest.cob's single 88-level branch and feecalc.cob's flat
      * EVALUATE lookup. Still truncates toward zero (no ROUNDED clause,
      * T1) and still reads a SIGN TRAILING SEPARATE numeric field (T6),
      * so it shares those two trap classes while genuinely differing in
      * shape -- the same "structurally similar, superficially
      * different" property FEECALC was built for (S1), applied to
      * control flow instead of arithmetic.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAXCALC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAX-FILE ASSIGN TO "tax.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "tax.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TAX-FILE.
           COPY "TAX-REC.cpy".

       FD  REPORT-FILE.
       01  TAX-REPORT-LINE.
           05  XL-ID              PIC X(16).
           05  XL-INCOME          PIC -(9)9.99.
           05  XL-TAX             PIC -(7)9.99.
       01  TAX-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-TAX                 PIC S9(7)V99.
       01  WS-TOTAL-TAX           PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TAX-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ TAX-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-TAX
               END-READ
           END-PERFORM

           MOVE "TOTAL TAX:" TO TL-LABEL
           MOVE WS-TOTAL-TAX TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE TAX-TOTALS-LINE

           CLOSE TAX-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-TAX.
           IF TR-INCOME > 100000.00
               COMPUTE WS-TAX = TR-INCOME * 0.30
           ELSE
               IF TR-INCOME > 50000.00
                   COMPUTE WS-TAX = TR-INCOME * 0.20
               ELSE
                   IF TR-INCOME > 20000.00
                       COMPUTE WS-TAX = TR-INCOME * 0.10
                   ELSE
                       COMPUTE WS-TAX = TR-INCOME * 0.05
                   END-IF
               END-IF
           END-IF

           ADD WS-TAX TO WS-TOTAL-TAX

           MOVE TR-ID       TO XL-ID
           MOVE TR-INCOME   TO XL-INCOME
           MOVE WS-TAX      TO XL-TAX
           WRITE TAX-REPORT-LINE.
