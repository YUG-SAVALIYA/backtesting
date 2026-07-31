import urllib.request, json
payload = {'companies': '360ONE', 'start_date': '22062026', 'end_date': '28072026'}
req = urllib.request.Request('http://127.0.0.1:8000/api/backtest', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            s = line.decode('utf-8')
            if '"error"' in s:
                print('ERROR EVENT:', s.strip()[:200])
            if '"complete"' in s:
                data = json.loads(s.replace('data: ', '').strip())
                print("TOTAL TRADES: " + str(len(data.get('signals', []))))
                print("ERRORS LENGTH: " + str(len(data.get('errors', []))))
except Exception as e:
    print(e)
