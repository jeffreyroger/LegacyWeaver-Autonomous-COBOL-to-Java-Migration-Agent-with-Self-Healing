      *****************************************************************
      * SHIP-REC — input record layout (Step U4).
      *
      * SR-WEIGHT and SR-ZONE are both read by a single EVALUATE TRUE
      * WHEN clause's compound AND condition in COMPUTE-SHIPCOST -- a
      * shape none of the other fixtures use (feecalc.cob's EVALUATE
      * switches on one field; taxcalc.cob's IF/ELSE ladder thresholds
      * one field). No SIGN TRAILING SEPARATE field here (weight is
      * never negative) -- deliberately drops that trap class to isolate
      * the compound-condition shape as the only thing under test.
      *
      *   Field        Offset  Width  PIC                          Notes
      *   SR-ID          0       16     X(16)
      *   SR-WEIGHT      16      7      9(5)V99                     unsigned
      *   SR-ZONE        23      1      X(1)                        'A'/'B'/other
      *   SR-FILLER      24      6      X(6)                        record shape only, unused
      *   -------------------------------------------------------------
      *   TOTAL                  30
      *****************************************************************
       01  SHIP-REC.
           05  SR-ID              PIC X(16).
           05  SR-WEIGHT          PIC 9(5)V99.
           05  SR-ZONE            PIC X(1).
           05  SR-FILLER          PIC X(6).
