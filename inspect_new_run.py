import json

with open(r'c:\Users\Yug\Desktop\rsi\output\backtest_2026-07-29_21-35-31_3008stocks.json') as f:
    data = json.load(f)

signals = data.get('signals', [])
settings = data.get('settings', {})

print('=== SETTINGS ===')
print(json.dumps(settings, indent=2))
print(f'\n=== TOTAL TRADES: {len(signals)} ===')

# Check if HIRECT and MSPL are present
for s in signals:
    sym = s.get('company', '?')
    if sym in ('HIRECT', 'MSPL'):
        print(f'\n*** FOUND: {sym} ***')
        print(json.dumps({k: v for k, v in s.items() if k in [
            'company', 'entry_time', 'signal_time', 'signal_date',
            'close_lookahead', 'close_lookahead_pct', 'max_high_lookahead',
            'max_high_lookahead_pct', 'sl_hit_lookahead', 'pre_final_status',
            'adx', 'rsi', 'candle_range_pct'
        ]}, indent=2))

print('\n=== ALL TRADES ===')
for s in signals:
    sym = s.get('company', '?')
    dt = str(s.get('entry_time', s.get('signal_date', '?')))[:10]
    pf_status = s.get('pre_final_status', 'N/A')
    print(f'  {sym:15s} | {dt} | pre_final={pf_status}')
