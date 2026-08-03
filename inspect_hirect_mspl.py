import json

with open(r'c:\Users\Yug\Desktop\rsi\output\backtest_2026-07-29_21-35-31_3008stocks.json') as f:
    data = json.load(f)

signals = data.get('signals', [])

# Print ALL fields for HIRECT and MSPL - need to find what entry/original_entry/signal_high are
for s in signals:
    sym = s.get('company', '?')
    if sym in ('HIRECT', 'MSPL'):
        print(f'\n{"="*60}')
        print(f'ALL FIELDS FOR: {sym}')
        print(f'{"="*60}')
        for k, v in sorted(s.items()):
            if v is not None:
                print(f'  {k:35s} = {v}')
