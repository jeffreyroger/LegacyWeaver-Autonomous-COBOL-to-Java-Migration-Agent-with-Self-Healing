      *****************************************************************
      * TAX-REC — input record layout (Step U1).
      *
      * Shares TR-INCOME's SIGN TRAILING SEPARATE shape with interest.cob
      * and feecalc.cob's balance fields (same encoding trap, T6), but the
      * paragraph that consumes it (COMPUTE-TAX) is a nested IF/ELSE
      * bracket ladder instead of either program's flat lookup -- a
      * different control-flow shape entirely (Step U1).
      *
      *   Field        Offset  Width  PIC                          Notes
      *   TR-ID          0       16     X(16)
      *   TR-INCOME      16      12     9(9)V99 SIGN TRAILING SEP.
      *   TR-BRACKET     28      1      X(1)                        unused by logic, record shape only
      *   TR-ACTIVE      29      1      X(1)
      *   -------------------------------------------------------------
      *   TOTAL                  30
      *****************************************************************
       01  TAX-REC.
           05  TR-ID              PIC X(16).
           05  TR-INCOME          PIC S9(9)V99
               SIGN IS TRAILING SEPARATE.
           05  TR-BRACKET         PIC X(1).
           05  TR-ACTIVE          PIC X(1).
