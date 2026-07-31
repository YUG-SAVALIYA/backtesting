import json
with open('live_trades.json', 'r') as f:
    trades = json.load(f)
for t in trades:
    if t['company'] in ('HINDALCO', 'SUNPHARMA') and t['status'] in ('ENTRY_PENDING', 'ACTIVE'):
        print(f"{t['company']} ({t['status']}): Entry {t['entry_price']} | SL {t['stoploss_price']}")
