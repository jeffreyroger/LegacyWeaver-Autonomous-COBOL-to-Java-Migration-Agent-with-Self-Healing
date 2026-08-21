      *****************************************************************
      * VALIDATION.CBL -- Phase BB4 fixture (proactive generalization
      * of weaver/cobol/frontend.py beyond one-input/one-output,
      * migration-framework-spec.md's proactive-generalization request).
      * A validation/summary-only program: no output file at all, just
      * a running total of every record's balance, DISPLAYed once at
      * the end. See weaver/agent/scaffold.py's summary_accumulator_width
      * comment for the exact (deliberately narrow) subshape -- one
      * unsigned accumulator, one single-argument DISPLAY, no per-record
      * output.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALIDATION.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO "accounts4.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01  ACCOUNT-REC.
           05  AC-ID                  PIC X(10).
           05  AC-BALANCE             PIC 9(7)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG                PIC X VALUE 'N'.
           88  WS-EOF                 VALUE 'Y'.
       01  WS-BALANCE-COPY            PIC 9(7)V99.
       01  WS-TOTAL-BALANCE           PIC 9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE

           PERFORM UNTIL WS-EOF
               READ ACCOUNT-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM SUM-BALANCE
               END-READ
           END-PERFORM

           CLOSE ACCOUNT-FILE
           DISPLAY WS-TOTAL-BALANCE.
           STOP RUN.

       SUM-BALANCE.
           MOVE AC-BALANCE TO WS-BALANCE-COPY
           ADD WS-BALANCE-COPY TO WS-TOTAL-BALANCE.
