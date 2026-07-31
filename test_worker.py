
import json
import sys
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.core.backtest_worker import process_single_company_worker

req = json.load(open('c:/Users/Yug/Desktop/rsi/last_request.json'))
task = {
    'company': 'MODISONLTD',
    'req_dict': req,
    'data_dir': 'c:/Users/Yug/Desktop/rsi/data'
}
res = process_single_company_worker(task)
if res['error']:
    print('Error:', res['error'])
else:
    print('Base signals:', len(res['base_signals']))
    print('Final executed trades:', len(res['trades']))
    for t in res['trades']:
        print('Trade:', t)
