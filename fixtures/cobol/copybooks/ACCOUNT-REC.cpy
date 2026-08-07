      *****************************************************************
      * ACCOUNT-REC — input record layout (SRS §5.1; Step B1).
      *
      * Hand-derived offset table (0-based byte offsets, 39-byte record):
      *
      *   Field           Offset  Width  PIC                          Notes
      *   AR-ID           0       16     X(16)
      *   AR-BALANCE      16      12     9(9)V99 SIGN TRAILING SEP.   T2, T6 (11 digits + 1 sign byte)
      *   AR-RATE         28      6      9V9(5)                       T2 (implied decimal, 0 stored bytes for V)
      *   AR-TYPE         34      1      X(1)                         drives 88-level AR-PREMIUM (T4)
      *   AR-FLAGS        35      4      X(4)                         T3 overlay target
      *     AR-DORMANT    35      1      (via REDEFINES)              T3
      *     AR-HOLD       36      1      (via REDEFINES)              T3
      *     FILLER        37      2      (via REDEFINES)
      *   -------------------------------------------------------------
      *   TOTAL                  39
      *
      * Verified independently against weaver/layout.py:INPUT_LAYOUT
      * (Step B1 acceptance test: two independently derived tables agree
      * on a total record length of 39 bytes).
      *****************************************************************
       01  ACCOUNT-REC.
           05  AR-ID              PIC X(16).
           05  AR-BALANCE         PIC S9(9)V99
               SIGN IS TRAILING SEPARATE.
           05  AR-RATE            PIC 9V9(5).
           05  AR-TYPE            PIC X(1).
               88  AR-PREMIUM     VALUE 'P'.
           05  AR-FLAGS.
               10  AR-FLAG-BYTES  PIC X(4).
           05  AR-FLAGS-R REDEFINES AR-FLAGS.
               10  AR-DORMANT     PIC X(1).
                   88  AR-IS-DORMANT VALUE 'Y'.
               10  AR-HOLD        PIC X(1).
                   88  AR-IS-HOLD VALUE 'Y'.
               10  FILLER         PIC X(2).
