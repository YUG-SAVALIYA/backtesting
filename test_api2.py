import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

payload = {'companies': 'ALL', 'start_date': '2021-01-01', 'end_date': '2026-12-31', 'universe': 'ALL'}
req = urllib.request.Request('http://127.0.0.1:8000/api/backtest', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})

with urllib.request.urlopen(req, context=ctx) as response:
    for line in response:
        line_str = line.decode('utf-8')
        if '"complete"' in line_str:
            try:
                data = json.loads(line_str.replace('data: ', '').strip())
                print(f'Total signals generated from endpoint: {len(data.get("signals", []))}')
            except Exception as e:
                print(f'Error parsing final line: {e}')
