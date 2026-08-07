if (ar.tier.equals("A")) {
    ws.rate = new java.math.BigDecimal("0.01500");
} else if (ar.tier.equals("B")) {
    ws.rate = new java.math.BigDecimal("0.01000");
} else {
    ws.rate = new java.math.BigDecimal("0.00500");
}

ws.fee = ar.balance.negate().multiply(ws.rate).setScale(2, java.math.RoundingMode.DOWN);
