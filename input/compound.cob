      *****************************************************************
      * COMPOUND.CBL — Step U3's pure-arithmetic program.
      *
      * COMPUTE-COMPOUND is a straight-line chain of four sequential
      * COMPUTE statements, each depending on the previous step's
      * result -- no IF, EVALUATE, or PERFORM anywhere in the paragraph.
      * Different from every prior fixture (interest.cob's 88-level
      * branch, feecalc.cob's flat EVALUATE, taxcalc.cob's nested
      * IF/ELSE, tieraccum.cob's in-paragraph loop): the divergence risk
      * here is purely chained truncation across four steps, never a
      * wrong branch taken. Still truncates toward zero at every step
      * (no ROUNDED, T1) and reads a SIGN TRAILING SEPARATE numeric
      * field (T6).
      * Retrigger: workflow no longer stops the loop when one program fails or escalates -- refiring so all six promoted programs actually run.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPOUND.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT COMPOUND-FILE ASSIGN TO "compound.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "compound.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  COMPOUND-FILE.
           COPY "COMPOUND-REC.cpy".

       FD  REPORT-FILE.
       01  COMPOUND-REPORT-LINE.
           05  DL-ID              PIC X(16).
           05  DL-PRINCIPAL       PIC -(9)9.99.
           05  DL-RESULT          PIC -(7)9.99.
       01  COMPOUND-TOTALS-LINE.
           05  TL-LABEL           PIC X(30).
           05  TL-TOTAL           PIC -(7)9.99.
           05  TL-FILLER          PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-STEP1               PIC S9(7)V99.
       01  WS-STEP2               PIC S9(7)V99.
       01  WS-STEP3               PIC S9(7)V99.
       01  WS-STEP4               PIC S9(7)V99.
       01  WS-RESULT              PIC S9(7)V99.
       01  WS-TOTAL-RESULT        PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT COMPOUND-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ COMPOUND-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM COMPUTE-COMPOUND
               END-READ
           END-PERFORM

           MOVE "TOTAL RESULT:" TO TL-LABEL
           MOVE WS-TOTAL-RESULT TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE COMPOUND-TOTALS-LINE

           CLOSE COMPOUND-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       COMPUTE-COMPOUND.
           COMPUTE WS-STEP1 = CP-PRINCIPAL * 0.05
           COMPUTE WS-STEP2 = WS-STEP1 + CP-PRINCIPAL
           COMPUTE WS-STEP3 = WS-STEP2 * 0.03
           COMPUTE WS-STEP4 = CP-PRINCIPAL * 0.01
           COMPUTE WS-RESULT = WS-STEP2 + WS-STEP3 - WS-STEP4.

           ADD WS-RESULT TO WS-TOTAL-RESULT

           MOVE CP-ID         TO DL-ID
           MOVE CP-PRINCIPAL  TO DL-PRINCIPAL
           MOVE WS-RESULT     TO DL-RESULT
           WRITE COMPOUND-REPORT-LINE.
