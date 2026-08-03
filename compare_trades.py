import json
import re

with open('c:/Users/Yug/Desktop/rsi/tradesignal_results.txt', 'r', encoding='utf-16') as f:
    lines = f.readlines()

ts_signals = set()
for line in lines:
    if '15:30:00' in line:
        parts = line.split()
        # format: index symbol date time status entry stop target
        # parts[1] is symbol, parts[2] is date
        if len(parts) >= 3:
            sym = parts[1].replace('.NS', '')
            date = parts[2]
            ts_signals.add((sym, date))

print(f"Parsed {len(ts_signals)} tradesignal signals.")

import os
if os.path.exists('c:/Users/Yug/Desktop/rsi/backtester_all_trades.json'):
    with open('c:/Users/Yug/Desktop/rsi/backtester_all_trades.json', 'r') as f:
        bt_data = json.load(f)
    
    bt_signals = set()
    for t in bt_data:
        sym = t['symbol'].replace('.NS', '')
        date = t['signal_time'][:10]
        bt_signals.add((sym, date))
        
    print(f"Parsed {len(bt_signals)} backtester signals.")
    
    only_in_ts = ts_signals - bt_signals
    only_in_bt = bt_signals - ts_signals
    
    print(f"\nSignals ONLY in tradesignal ({len(only_in_ts)}):")
    for s in sorted(only_in_ts):
        print(f"  {s}")
        
    print(f"\nSignals ONLY in backtester ({len(only_in_bt)}):")
    for s in sorted(only_in_bt):
        print(f"  {s}")
else:
    print("backtester_all_trades.json not found yet.")
