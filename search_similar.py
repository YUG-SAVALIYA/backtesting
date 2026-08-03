import json
with open('live_trades.json', 'r') as f:
    trades = json.load(f)
for t in trades:
    if any(k in t['company'] for k in ('SUN', 'PHARMA', 'HIND')):
        print(f"{t['company']} ({t['status']}): SL={t.get('stoploss_price')} Entry={t.get('entry_price')}")
