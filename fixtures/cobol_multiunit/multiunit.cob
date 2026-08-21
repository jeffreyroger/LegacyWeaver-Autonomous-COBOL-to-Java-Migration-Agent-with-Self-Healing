      *****************************************************************
      * MULTIUNIT.CBL -- Phase BB3 fixture (proactive generalization of
      * weaver/cobol/frontend.py beyond one-input/one-output/one-unit,
      * migration-framework-spec.md's proactive-generalization request).
      * Two distinct business-logic paragraphs PERFORMed once each per
      * record: VALIDATE-RECORD sets a status field, COMPUTE-FEE computes
      * and writes the report line -- a validate-then-compute pair, each
      * independently synthesizable.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIUNIT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO "accounts3.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "multiunit.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01  ACCOUNT-REC.
           05  AC-ID                  PIC X(10).
           05  AC-BALANCE             PIC 9(7)V99.

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ID                  PIC X(10).
           05  RL-CODE                PIC -(1)9.99.
           05  RL-FEE                 PIC -(7)9.99.
       01  TOTALS-LINE.
           05  TL-LABEL               PIC X(30).
           05  TL-TOTAL               PIC -(7)9.99.
           05  TL-FILLER              PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG                PIC X VALUE 'N'.
           88  WS-EOF                 VALUE 'Y'.
       01  WS-VALID-CODE              PIC 9V99.
       01  WS-FEE                     PIC S9(7)V99.
       01  WS-TOTAL-FEE               PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ ACCOUNT-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM VALIDATE-RECORD
                       PERFORM COMPUTE-FEE
               END-READ
           END-PERFORM

           MOVE "TOTAL FEE:" TO TL-LABEL
           MOVE WS-TOTAL-FEE TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE TOTALS-LINE

           CLOSE ACCOUNT-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       VALIDATE-RECORD.
           IF AC-BALANCE > 0
               MOVE 1 TO WS-VALID-CODE
           ELSE
               MOVE 0 TO WS-VALID-CODE
           END-IF
           MOVE AC-ID TO RL-ID
           MOVE WS-VALID-CODE TO RL-CODE.

       COMPUTE-FEE.
           COMPUTE WS-FEE = AC-BALANCE * 0.01000
           ADD WS-FEE TO WS-TOTAL-FEE
           MOVE WS-FEE TO RL-FEE
           WRITE REPORT-LINE.
