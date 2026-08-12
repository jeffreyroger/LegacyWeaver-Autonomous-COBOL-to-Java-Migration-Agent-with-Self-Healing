if (ar.weight.compareTo(new java.math.BigDecimal("50.00")) > 0 && ar.priority.equals("H")) {
    ws.fee = ar.weight.multiply(new java.math.BigDecimal("0.60")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.weight.compareTo(new java.math.BigDecimal("50.00")) > 0 && ar.priority.equals("L")) {
    ws.fee = ar.weight.multiply(new java.math.BigDecimal("0.40")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.weight.compareTo(new java.math.BigDecimal("50.00")) <= 0 && ar.priority.equals("H")) {
    ws.fee = ar.weight.multiply(new java.math.BigDecimal("0.35")).setScale(2, java.math.RoundingMode.DOWN);
} else {
    ws.fee = ar.weight.multiply(new java.math.BigDecimal("0.20")).setScale(2, java.math.RoundingMode.DOWN);
}
