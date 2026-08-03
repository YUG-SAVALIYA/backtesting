import requests, json

payload = {
    'companies': 'ALL',
    'start_date': '2026-06-15',
    'end_date': '2026-07-28',
    'ltf': 'Day',
    'htf': 'Week',
    'supertrend_period': 21,
    'supertrend_multiplier': 1.5,
    'htf_supertrend_period': 14,
    'htf_supertrend_multiplier': 1.0,
    'rsi_ltf_period': 14,
    'rsi_ltf_min': 65.0,
    'rsi_ltf_max': 90.0,
    'rsi_htf_period': 14,
    'rsi_htf_min': 60.0,
    'rsi_htf_max': 85.0,
    'target_level': 20,
    'look_forward_limit': 1575,
    'entry_lookahead_bars': 1,
    'max_stoploss_pct': 5.0,
    'stoploss_mode': 'signal_candle_low',
    'max_parallel': 1,
    'target_mode': 'fixed',
    'atr_multiplier': 2.0,
    'entry_offset_pct': 0.0,   # No gap requirement - show ALL entries
    'min_adx': 0.0,            # No filters during generation - apply them via UI
    'min_candle_range': 0.0,
    'max_candle_range': 100.0,
    'trade_management_enabled': True,
    'trade_management_book_pct': 50.0,
    'trade_management_trigger_pct': 10.0,
    'trade_management_targets': [{'book_pct': 50.0, 'trigger_pct': 10.0, 'stoploss_pct': 0.0}]
}

print('Sending request...')
r = requests.post('http://127.0.0.1:8000/api/backtest', json=payload, stream=True, timeout=600)
signals = []
for line in r.iter_lines():
    if line:
        raw = line.decode('utf-8')
        if raw.startswith('data: '):
            try:
                obj = json.loads(raw[6:])
                if obj.get('type') == 'complete':
                    signals = obj.get('signals', [])
                    print(f'Found {len(signals)} signals')
                    break
            except:
                pass

out = {
    'signals': signals,
    'baseSignals': signals,
    'selectedEntryLookaheadBars': 1,
    'settings': payload,
    'timeTaken': 0
}
with open('c:/Users/Yug/Desktop/rsi/tradesignal_comparison_results.json', 'w') as f:
    json.dump(out, f)
print('Saved!')
