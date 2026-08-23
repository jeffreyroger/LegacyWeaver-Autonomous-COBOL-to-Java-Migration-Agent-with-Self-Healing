        // Reference translation of ROOT.cob's PROCESS-RECORD:
        //   CALL "LEAF-A" USING IN-AMOUNT WS-OUTPUT-A   (doubles the amount)
        //   CALL "LEAF-B" USING IN-AMOUNT WS-OUTPUT-B   (adds a 10.00 surcharge)
        // LEAF-A/LEAF-B have no Java counterpart in this single-program
        // scaffold -- attribution.py's verify_unit always overwrites this
        // body at spec.reference_paragraph_id before assembly (PROCESS-RECORD
        // is ROOT's only unit), so this file exists to be a real, correct
        // reference for the human reader, not a load-bearing runtime input.
        ws.outputA = ar.amount.multiply(new java.math.BigDecimal("2")).setScale(2, java.math.RoundingMode.UNNECESSARY);
        ws.outputB = ar.amount.add(new java.math.BigDecimal("10.00"));
