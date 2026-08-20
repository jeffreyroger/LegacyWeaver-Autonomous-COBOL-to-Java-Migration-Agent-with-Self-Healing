      *****************************************************************
      * MULTIINPUT.CBL -- Phase BB1 fixture (proactive generalization of
      * weaver/cobol/frontend.py beyond its original one-input/one-output
      * scope, migration-framework-spec.md's proactive-generalization
      * request). A driving loop that reads TWO input files in lockstep
      * by position (no key matching -- see ScaffoldSpec.extra_input_files'
      * own comment for why this is a deliberately narrower subshape than
      * a full COBOL MATCH-MERGE), one master balance record paired each
      * iteration with one adjustment record from a separate file.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIINPUT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO "master.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT ADJUST-FILE ASSIGN TO "adjust.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "multiinput.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE.
       01  MASTER-REC.
           05  MST-ID                 PIC X(10).
           05  MST-BALANCE            PIC 9(7)V99.

       FD  ADJUST-FILE.
       01  ADJUST-REC.
           05  ADJ-ID                 PIC X(10).
           05  ADJ-AMOUNT             PIC 9(5)V99.

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ID                  PIC X(10).
           05  RL-BALANCE             PIC -(9)9.99.
           05  RL-ADJUSTED            PIC -(7)9.99.
       01  TOTALS-LINE.
           05  TL-LABEL               PIC X(30).
           05  TL-TOTAL               PIC -(7)9.99.
           05  TL-FILLER              PIC X(1).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG                PIC X VALUE 'N'.
           88  WS-EOF                 VALUE 'Y'.
       01  WS-ADJUSTED                PIC S9(7)V99.
       01  WS-TOTAL-ADJUSTED          PIC S9(9)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT MASTER-FILE
           OPEN INPUT ADJUST-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ MASTER-FILE
                   AT END
                       SET WS-EOF TO TRUE
               END-READ
               IF NOT WS-EOF
                   READ ADJUST-FILE
                       AT END
                           SET WS-EOF TO TRUE
                   END-READ
               END-IF
               IF NOT WS-EOF
                   PERFORM PROCESS-RECORD
               END-IF
           END-PERFORM

           MOVE "TOTAL ADJUSTED:" TO TL-LABEL
           MOVE WS-TOTAL-ADJUSTED TO TL-TOTAL
           MOVE SPACE TO TL-FILLER
           WRITE TOTALS-LINE

           CLOSE MASTER-FILE
           CLOSE ADJUST-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       PROCESS-RECORD.
           COMPUTE WS-ADJUSTED = MST-BALANCE + ADJ-AMOUNT
           ADD WS-ADJUSTED TO WS-TOTAL-ADJUSTED
           MOVE MST-ID TO RL-ID
           MOVE MST-BALANCE TO RL-BALANCE
           MOVE WS-ADJUSTED TO RL-ADJUSTED
           WRITE REPORT-LINE.
