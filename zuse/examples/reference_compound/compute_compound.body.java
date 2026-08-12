java.math.BigDecimal step1 = ar.principal.multiply(new java.math.BigDecimal("0.05"))
    .setScale(2, java.math.RoundingMode.DOWN);
java.math.BigDecimal step2 = step1.add(ar.principal);
java.math.BigDecimal step3 = step2.multiply(new java.math.BigDecimal("0.03"))
    .setScale(2, java.math.RoundingMode.DOWN);
java.math.BigDecimal step4 = ar.principal.multiply(new java.math.BigDecimal("0.01"))
    .setScale(2, java.math.RoundingMode.DOWN);

ws.result = step2.add(step3).subtract(step4);
