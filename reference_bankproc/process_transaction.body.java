ws.amount = ar.amount;

if (ar.isDeposit()) {
    ws.balance = ws.balance.add(ws.amount);
} else {
    if (ws.amount.compareTo(ws.balance) <= 0) {
        ws.balance = ws.balance.subtract(ws.amount);
    }
}
