import urllib.request, json
payload = {'companies': 'ALL', 'start_date': '2026-06-22', 'end_date': '2026-07-28', 'entry_lookahead_bars': 1}
req = urllib.request.Request('http://127.0.0.1:8000/api/backtest', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            s = line.decode('utf-8')
            if '\"complete\"' in s:
                data = json.loads(s.replace('data: ', '').strip())
                print("TOTAL TRADES (1 bar): " + str(len(data.get('signals', []))))
except Exception as e:
    print(e)
