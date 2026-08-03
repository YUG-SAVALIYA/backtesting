import json
with open('live_trades.json', 'r') as f:
    trades = json.load(f)
for t in trades:
    if t['company'] == 'TMPV' and t['status'] == 'ACTIVE':
        print(f"TMPV target_order_id: {t.get('target_order_id')}")
