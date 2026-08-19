      *****************************************************************
      * ROOT.CBL -- Task 6 multi-program fixture (FR-13.4).
      *
      * Root program driving the leaf-first migration/verification
      * pipeline (migration-framework-spec.md Section 5). Reads one
      * numeric amount per input record, CALLs LEAF-A (double) and
      * LEAF-B (surcharge +10.00) with real LINKAGE-SECTION parameter
      * passing, and writes both results to one report line.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ROOT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO "accounts.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE  ASSIGN TO "multiprog.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-FILE.
       01  IN-REC.
           05  IN-ID              PIC X(6).
           05  IN-AMOUNT          PIC 9(5)V99.

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ID              PIC X(6).
           05  RL-A               PIC -(7)9.99.
           05  RL-B               PIC -(7)9.99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-OUTPUT-A            PIC 9(5)V99.
       01  WS-OUTPUT-B            PIC 9(5)V99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT ACCOUNT-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ ACCOUNT-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM PROCESS-RECORD
               END-READ
           END-PERFORM

           CLOSE ACCOUNT-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       PROCESS-RECORD.
           CALL "LEAF-A" USING IN-AMOUNT WS-OUTPUT-A
           CALL "LEAF-B" USING IN-AMOUNT WS-OUTPUT-B

           MOVE IN-ID       TO RL-ID
           MOVE WS-OUTPUT-A TO RL-A
           MOVE WS-OUTPUT-B TO RL-B
           WRITE REPORT-LINE.
