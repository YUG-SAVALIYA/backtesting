import json
import pandas as pd

json_path = r"c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-13-38-48.json"
with open(json_path) as f:
    data = json.load(f)

signals = data.get('signals', [])
print(f"Total signals in filtered JSON: {len(signals)}")

trade_list = []
for s in signals:
    sym = s.get('company')
    sig_date = str(s.get('signal_date'))[:10]
    entry_date = str(s.get('entry_time'))[:10]
    entry = s.get('new_entry') or s.get('entry')
    target = s.get('new_target') or s.get('Target')
    stoploss = s.get('new_stoploss') or s.get('Stoploss')
    exit_type = s.get('exit_type')
    exit_price = s.get('exit_price')
    pnl = s.get('trade_management_weighted_return_pct') if s.get('trade_management_weighted_return_pct') is not None else s.get('pnl_pct')
    
    trade_list.append({
        'symbol': sym,
        'signal_date': sig_date,
        'entry_date': entry_date,
        'entry_price': entry,
        'target': target,
        'stoploss': stoploss,
        'exit_price': exit_price,
        'exit_type': exit_type,
        'pnl_pct': pnl
    })

df = pd.DataFrame(trade_list)
print("\n=== TRADES IN FILTERED JSON (Gap-Up + SL/Target Update) ===")
print(df.to_string())
