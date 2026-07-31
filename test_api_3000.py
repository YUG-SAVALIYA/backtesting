import urllib.request, json
import pandas as pd
import time
df = pd.read_csv('d:/AT/AI_Trading/data/companies_1yr_daily_candles.csv', usecols=['symbol'])
symbols = sorted(df['symbol'].unique())
payload = {'companies': ','.join(symbols), 'start_date': '2026-06-22', 'end_date': '2026-07-28'}
req = urllib.request.Request('http://127.0.0.1:8000/api/backtest', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
t0 = time.time()
try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            s = line.decode('utf-8')
            if '"complete"' in s:
                data = json.loads(s.replace('data: ', '').strip())
                print('TOTAL TRADES:', len(data.get('signals', [])))
                print('TIME:', time.time() - t0)
except Exception as e:
    print(e)
