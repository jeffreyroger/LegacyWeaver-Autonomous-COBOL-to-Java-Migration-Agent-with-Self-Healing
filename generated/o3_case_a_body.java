if (ar.isPremium()) {
    ws.appliedRate = ar.rate.multiply(new java.math.BigDecimal("1.15"))
        .setScale(5, java.math.RoundingMode.DOWN);
} else {
    ws.appliedRate = ar.rate.setScale(5, java.math.RoundingMode.DOWN);
}

if (ar.isDormant()) {
    ws.interest = java.math.BigDecimal.ZERO.setScale(2);
} else {
    ws.interest = ar.balance.multiply(ws.appliedRate)
        .divide(new java.math.BigDecimal(365), 10, java.math.RoundingMode.DOWN)
        .setScale(2, java.math.RoundingMode.DOWN).multiply(new java.math.BigDecimal("10"));
}
