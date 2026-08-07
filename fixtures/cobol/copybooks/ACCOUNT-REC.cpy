      *****************************************************************
      * ACCOUNT-REC — input record layout (SRS §5.1)
      * TODO(Step B1): derive the byte-offset table by hand before
      * filling in this copybook. Total record length must be 39 bytes.
      *
      * Planted constructs referenced here:
      *   T2 — implied decimal position (PIC 9(n)V9(m), no stored '.')
      *   T3 — REDEFINES overlay on the flag group
      *   T6 — trailing separate sign on the balance field
      *****************************************************************
       01  ACCOUNT-REC.
      *    TODO: 05 AR-ID           PIC X(...).
      *    TODO: 05 AR-BALANCE      PIC 9(...)V9(...) SIGN IS TRAILING SEPARATE.
      *    TODO: 05 AR-RATE         PIC 9(...)V9(...).
      *    TODO: 05 AR-TYPE         PIC X(...).
      *    TODO: 05 AR-FLAGS.
      *    TODO:    10 AR-FLAG-BYTES PIC X(4).
      *    TODO: 05 AR-FLAGS-R REDEFINES AR-FLAGS.
      *    TODO:    10 AR-DORMANT   PIC X(1).
      *    TODO:    10 AR-HOLD      PIC X(1).
      *    TODO:    10 FILLER       PIC X(2).
