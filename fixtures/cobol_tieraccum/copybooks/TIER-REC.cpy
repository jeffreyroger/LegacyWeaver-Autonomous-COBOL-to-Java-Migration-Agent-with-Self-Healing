      *****************************************************************
      * TIER-REC — input record layout (Step U2).
      *
      * UR-UNITS drives an in-paragraph PERFORM VARYING loop in
      * ACCUMULATE-TIERS -- a control-flow shape none of interest.cob,
      * feecalc.cob, or taxcalc.cob use (their only loop is the
      * scaffold's per-record main loop; this program's synthesis unit
      * has a loop of its own).
      *
      *   Field        Offset  Width  PIC                          Notes
      *   UR-ID          0       16     X(16)
      *   UR-BASE        16      12     9(9)V99 SIGN TRAILING SEP.
      *   UR-UNITS       28      2      9(2)                        number of tiers to accumulate, 1-5
      *   -------------------------------------------------------------
      *   TOTAL                  30
      *****************************************************************
       01  TIER-REC.
           05  UR-ID              PIC X(16).
           05  UR-BASE            PIC S9(9)V99
               SIGN IS TRAILING SEPARATE.
           05  UR-UNITS           PIC 9(2).
