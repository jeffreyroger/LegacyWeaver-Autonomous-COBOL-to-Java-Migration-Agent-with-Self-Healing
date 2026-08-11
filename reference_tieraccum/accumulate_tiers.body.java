ws.accum = java.math.BigDecimal.ZERO.setScale(2);

int units = ar.units.intValueExact();
for (int idx = 1; idx <= units; idx++) {
    java.math.BigDecimal step = ar.base.multiply(new java.math.BigDecimal("0.10"))
        .divide(new java.math.BigDecimal(idx), 2, java.math.RoundingMode.DOWN);
    ws.accum = ws.accum.add(step);
}
