      *****************************************************************
      * BANKPROC.CBL — batch account transaction processor, rewritten
      * to fit this repo's Phase U frontend scope (weaver/cobol/
      * frontend.py): exactly one input file, one output file, one
      * 01-level input record, exactly two 01-levels on the output file
      * (detail line then totals line), and exactly two paragraphs --
      * one driver, one synthesis unit.
      *
      * The original test3.cob was an interactive terminal program
      * (ACCEPT/DISPLAY, no file I/O at all) -- a shape this harness
      * cannot model regardless of size, since its entire verification
      * contract is a byte-for-byte comparison of two programs' *file*
      * output (SRS FR-10). This version keeps the domain (deposits and
      * withdrawals against a running balance, insufficient-funds
      * rejection) but drives it from a transaction file instead of
      * keyboard input, batch-processing every transaction in one run.
      *
      * Rules:
      *   - deposit (TX-IS-DEPOSIT 88-level true): balance increases by
      *     the transaction amount.
      *   - withdrawal exceeding the current balance: rejected (no
      *     overdraft in this version) -- balance is left unchanged,
      *     which is how a reader tells NSF apart from a successful
      *     withdrawal in the output (no separate status column: the
      *     scaffold generator only supports numeric working-storage
      *     fields, weaver/agent/scaffold.py's WorkingStorage class
      *     emits BigDecimal fields exclusively, so an alphanumeric
      *     "OK "/"NSF" status field has nowhere to be stored).
      *   - withdrawal within balance: balance decreases.
      * Retrigger: workflow no longer stops the loop when one program fails or escalates -- refiring so all six promoted programs actually run.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANKPROC.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANSACTION-FILE ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE      ASSIGN TO "bankproc.out"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TRANSACTION-FILE.
       01  TRANSACTION-RECORD.
           05  TX-ACCOUNT-ID      PIC X(10).
           05  TX-TYPE            PIC X(1).
               88  TX-IS-DEPOSIT  VALUE "D".
           05  TX-AMOUNT          PIC 9(7)V99.

       FD  REPORT-FILE.
       01  REPORT-LINE.
           05  RL-ACCOUNT         PIC X(10).
           05  RL-TYPE            PIC X(1).
           05  RL-AMOUNT          PIC -(7)9.99.
           05  RL-BALANCE         PIC -(9)9.99.
       01  TOTALS-LINE.
      *    Shares REPORT-FILE's buffer with REPORT-LINE (two 01-levels
      *    under one FD implicitly redefine each other), so TL-LABEL is
      *    set explicitly in MAIN-PARA rather than via VALUE.
           05  TL-LABEL           PIC X(20).
           05  TL-TOTAL           PIC -(9)9.99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG            PIC X VALUE 'N'.
           88  WS-EOF             VALUE 'Y'.
       01  WS-BALANCE             PIC 9(9)V99 VALUE ZERO.
       01  WS-AMOUNT              PIC 9(7)V99.
       01  WS-TOTAL-PROCESSED     PIC 9(11)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT TRANSACTION-FILE
           OPEN OUTPUT REPORT-FILE

           PERFORM UNTIL WS-EOF
               READ TRANSACTION-FILE
                   AT END
                       SET WS-EOF TO TRUE
                   NOT AT END
                       PERFORM PROCESS-TRANSACTION
               END-READ
           END-PERFORM

           MOVE "TOTAL PROCESSED:" TO TL-LABEL
           MOVE WS-TOTAL-PROCESSED TO TL-TOTAL
           WRITE TOTALS-LINE

           CLOSE TRANSACTION-FILE
           CLOSE REPORT-FILE
           STOP RUN.

       PROCESS-TRANSACTION.
           MOVE TX-AMOUNT TO WS-AMOUNT

           IF TX-IS-DEPOSIT
               ADD WS-AMOUNT TO WS-BALANCE
           ELSE
               IF WS-AMOUNT NOT > WS-BALANCE
                   SUBTRACT WS-AMOUNT FROM WS-BALANCE
               END-IF
           END-IF

           ADD WS-AMOUNT TO WS-TOTAL-PROCESSED

           MOVE TX-ACCOUNT-ID TO RL-ACCOUNT
           MOVE TX-TYPE       TO RL-TYPE
           MOVE WS-AMOUNT     TO RL-AMOUNT
           MOVE WS-BALANCE    TO RL-BALANCE
           WRITE REPORT-LINE.
