import urllib.request
import json
import ssl
import sys
import os

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

payload = {
    'universe': 'ALL',
    'companies': 'ALL',
    'start_date': '2026-06-22',
    'end_date': '2026-07-28',
    'rsi_htf_period': 14,
    'rsi_ltf_period': 14,
    'max_stoploss_pct': 5.0,
    'target_level': 15,
    'trade_management_enabled': True,
    'trade_management_targets': [
        {'book_pct': 50.0, 'trigger_pct': 10.0, 'stoploss_pct': 0.0}
    ]
}

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/backtest',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

print('Sending request to backend...')
try:
    with urllib.request.urlopen(req, context=ctx) as response:
        for line in response:
            s = line.decode('utf-8')
            if '"complete"' in s:
                data = json.loads(s.replace('data: ', '').strip())
                print(f"Total Trades: {len(data.get('signals', []))}")
                print("Backtest completed. Results should be in output/ directory.")
                sys.exit(0)
except Exception as e:
    print(f"Error: {e}")
