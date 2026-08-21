      *****************************************************************
      * MULTIOUTPUT.CBL -- Phase BB2 fixture (proactive generalization of
      * weaver/cobol/frontend.py beyond one-input/one-output,
      * migration-framework-spec.md's proactive-generalization request).
      * One input file, written unconditionally to TWO separate output
      * files each record -- a fee report and a separate balance-audit
      * log, each with its own totals line. See
      * weaver/agent/scaffold.py's ExtraOutputFile comment for why this
      * is unconditional-per-record, not conditional routing.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIOUTPUT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO "accounts2.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "fee.out"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT AUDIT-FILE ASSIGN TO "audit.out"
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
           05  RL-BALANCE             PIC -(9)9.99.
           05  RL-FEE                 PIC -(7)9.99.
       01  REPORT-TOTALS-LINE.
           05  RTL-LABEL              PIC X(30).
           05  RTL-TOTAL              PIC -(7)9.99.
           05  RTL-FILLER             PIC X(1).

       FD  AUDIT-FILE.
       01  AUDIT-LINE.
           05  AL-ID                  PIC X(10).
           05  AL-BALANCE             PIC -(9)9.99.
       01  AUDIT-TOTALS-LINE.
           05  ATL-LABEL              PIC X(30).
           05  ATL-TOTAL              PIC -(9)9.99.
           05  ATL-FILLER             PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG                PIC X VALUE 'N'.
           88  WS-EOF                 VALUE 'Y'.
       01  WS-FEE                     PIC S9(7)V99.
       01  WS-TOTAL-FEE               PIC S9(9)V99 VALUE ZERO.
       01  WS-BALANCE-COPY            PIC S9(7)V99.
       01  WS-TOTAL-BALANCE           PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE
           OPEN OUTPUT REPORT-FILE
           OPEN OUTPUT AUDIT-FILE

           PERFORM UNTIL WS-EOF
               READ ACCOUNT-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM PROCESS-RECORD
               END-READ
           END-PERFORM

           MOVE "TOTAL FEE:" TO RTL-LABEL
           MOVE WS-TOTAL-FEE TO RTL-TOTAL
           MOVE SPACE TO RTL-FILLER
           WRITE REPORT-TOTALS-LINE

           MOVE "TOTAL BALANCE:" TO ATL-LABEL
           MOVE WS-TOTAL-BALANCE TO ATL-TOTAL
           MOVE SPACE TO ATL-FILLER
           WRITE AUDIT-TOTALS-LINE

           CLOSE ACCOUNT-FILE
           CLOSE REPORT-FILE
           CLOSE AUDIT-FILE
           STOP RUN.

       PROCESS-RECORD.
           COMPUTE WS-FEE = AC-BALANCE * 0.01000
           ADD WS-FEE TO WS-TOTAL-FEE
           MOVE AC-BALANCE TO WS-BALANCE-COPY
           ADD WS-BALANCE-COPY TO WS-TOTAL-BALANCE

           MOVE AC-ID       TO RL-ID
           MOVE AC-BALANCE  TO RL-BALANCE
           MOVE WS-FEE      TO RL-FEE
           WRITE REPORT-LINE

           MOVE AC-ID       TO AL-ID
           MOVE AC-BALANCE  TO AL-BALANCE
           WRITE AUDIT-LINE.
