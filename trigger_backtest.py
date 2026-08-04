import urllib.request, json, sys, os, subprocess
import time
import glob

with open('last_request.json', 'r') as f:
    payload = json.load(f)

payload['start_date'] = '2024-06-15'
payload['end_date'] = '2024-07-28'

# Wait a bit just in case, then send request
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/backtest',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

print('Sending request to backtest API for 2024-06-15 to 2024-07-28...')
try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            s = line.decode('utf-8')
            if '"complete"' in s:
                data = json.loads(s.replace('data: ', '').strip())
                print(f"Total Trades Generated: {len(data.get('signals', []))}")
                break
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

print('Waiting a couple of seconds for file write...')
time.sleep(2)

print('Running calc_stats_final.py to get metrics...')
subprocess.run(['python', 'calc_stats_final.py'])
