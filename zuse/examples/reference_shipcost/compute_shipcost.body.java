if (ar.weight.compareTo(new java.math.BigDecimal("100.00")) > 0 && ar.zone.equals("A")) {
    ws.cost = ar.weight.multiply(new java.math.BigDecimal("0.50")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.weight.compareTo(new java.math.BigDecimal("100.00")) > 0 && ar.zone.equals("B")) {
    ws.cost = ar.weight.multiply(new java.math.BigDecimal("0.75")).setScale(2, java.math.RoundingMode.DOWN);
} else if (ar.weight.compareTo(new java.math.BigDecimal("100.00")) <= 0 && ar.zone.equals("A")) {
    ws.cost = ar.weight.multiply(new java.math.BigDecimal("0.30")).setScale(2, java.math.RoundingMode.DOWN);
} else {
    ws.cost = ar.weight.multiply(new java.math.BigDecimal("0.45")).setScale(2, java.math.RoundingMode.DOWN);
}
