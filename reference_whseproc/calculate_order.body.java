if (ar.isPremium()) {
    ws.discount = ar.quantity.multiply(ar.unitPrice)
        .multiply(new java.math.BigDecimal("0.10"))
        .setScale(2, java.math.RoundingMode.DOWN);
} else {
    ws.discount = java.math.BigDecimal.ZERO.setScale(2);
}

ws.orderTotal = ar.quantity.multiply(ar.unitPrice)
    .subtract(ws.discount)
    .setScale(2, java.math.RoundingMode.DOWN);
