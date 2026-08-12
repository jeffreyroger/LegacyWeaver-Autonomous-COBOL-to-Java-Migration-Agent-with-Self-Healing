if (ar.income.compareTo(new java.math.BigDecimal("100000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.30")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.income.compareTo(new java.math.BigDecimal("50000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.20")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.income.compareTo(new java.math.BigDecimal("20000.00")) > 0) {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.10")).setScale(2, java.math.RoundingMode.DOWN);
} else {
    ws.tax = ar.income.multiply(new java.math.BigDecimal("0.05")).setScale(2, java.math.RoundingMode.DOWN);
}
