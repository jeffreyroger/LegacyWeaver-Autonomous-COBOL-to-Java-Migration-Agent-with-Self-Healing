      *****************************************************************
      * HANDL-REC — input record layout.
      *
      * Same single-shape record class as SHIP-REC (compound AND
      * condition over two fields in one EVALUATE WHEN), renamed and
      * re-parameterised as a warehouse handling-fee calculation so the
      * source file itself is new to the repository.
      *
      *   Field         Offset  Width  PIC                          Notes
      *   HR-ID           0       16     X(16)
      *   HR-WEIGHT       16      7      9(5)V99                     unsigned
      *   HR-PRIORITY     23      1      X(1)                        'H'/'L'/other
      *   HR-FILLER       24      6      X(6)                        record shape only, unused
      *   -------------------------------------------------------------
      *   TOTAL                   30
      *****************************************************************
       01  HANDL-REC.
           05  HR-ID              PIC X(16).
           05  HR-WEIGHT          PIC 9(5)V99.
           05  HR-PRIORITY        PIC X(1).
           05  HR-FILLER          PIC X(6).
