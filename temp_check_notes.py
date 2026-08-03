import json
with open('live_trades.json', 'r') as f:
    trades = json.load(f)
for t in trades:
    if t['status'] == 'ACTIVE':
        print(f"{t['company']} ({t['status']}): {t['notes']}")
