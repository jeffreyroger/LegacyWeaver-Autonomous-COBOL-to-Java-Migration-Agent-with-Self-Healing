      *****************************************************************
      * COMPOUND-REC — input record layout (Step U3).
      *
      * Shares CP-PRINCIPAL's SIGN TRAILING SEPARATE shape with every
      * other fixture's balance field (T6), but COMPUTE-COMPOUND (the
      * paragraph that consumes it) has no IF, EVALUATE, or PERFORM at
      * all -- a straight-line chain of COMPUTE statements, unlike every
      * prior fixture (Step U3).
      *
      *   Field        Offset  Width  PIC                          Notes
      *   CP-ID          0       16     X(16)
      *   CP-PRINCIPAL   16      12     9(9)V99 SIGN TRAILING SEP.
      *   CP-FILLER      28      2      X(2)                        record shape only, unused
      *   -------------------------------------------------------------
      *   TOTAL                  30
      *****************************************************************
       01  COMPOUND-REC.
           05  CP-ID              PIC X(16).
           05  CP-PRINCIPAL       PIC S9(9)V99
               SIGN IS TRAILING SEPARATE.
           05  CP-FILLER          PIC X(2).
