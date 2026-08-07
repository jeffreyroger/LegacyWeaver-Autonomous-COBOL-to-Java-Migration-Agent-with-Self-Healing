      *****************************************************************
      * FEE-REC — input record layout (Step S1).
      *
      * Deliberately shares AR-BALANCE's SIGN TRAILING SEPARATE shape
      * with interest.cob's ACCOUNT-REC, but with different field names
      * and no REDEFINES/88-level tiering -- FEECALC exists to share the
      * SIGN-defect class with interest.cob under different field names,
      * proving the failure-memory signature is structural, not lexical.
      *
      *   Field        Offset  Width  PIC                          Notes
      *   FR-ID         0       16     X(16)
      *   FR-BALANCE    16      12     9(9)V99 SIGN TRAILING SEP.
      *   FR-TIER       28      1      X(1)                         'A'/'B'/other
      *   FR-ACTIVE     29      1      X(1)
      *   -------------------------------------------------------------
      *   TOTAL                 30
      *****************************************************************
       01  FEE-REC.
           05  FR-ID              PIC X(16).
           05  FR-BALANCE         PIC S9(9)V99
               SIGN IS TRAILING SEPARATE.
           05  FR-TIER            PIC X(1).
           05  FR-ACTIVE          PIC X(1).
