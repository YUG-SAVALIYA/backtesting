import json

with open(r'c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-15-45-59.json') as f:
    data = json.load(f)

signals = data.get('signals', [])
settings = data.get('settings', {})

print('=== SAVED FILE SETTINGS ===')
print(json.dumps(settings, indent=2))
print()
print(f'=== TOTAL TRADES IN FILE: {len(signals)} ===')
file_syms = []
for s in signals:
    sym = s.get('company', '?')
    dt = str(s.get('entry_time', s.get('signal_date', '?')))[:10]
    file_syms.append(sym)
    print(f'  {sym:15s} | {dt}')
