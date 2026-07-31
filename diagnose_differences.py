import sys
import os
import pandas as pd
from pathlib import Path

# Paths
rsi_backend = r"c:\Users\Yug\Desktop\rsi\src"
tradesignal_backend = r"c:\Users\Yug\Desktop\tradesignal\backend"

sys.path.insert(0, rsi_backend)

from rsi_supertrend_backtester.io.data_loader import MarketDataLoader

loader = MarketDataLoader(Path(r"C:\Users\Yug\Desktop\rsi\data"))

# List of 20 symbols involved in either project
symbols = ['AEGISLOG', 'APEXECO', 'BIKEWO', 'CARBORUNIV', 'CONSOFINVT', 'FCL', 'GUFICBIO', 'HONASA', 'KAMDHENU', 'KERNEX', 'MODISONLTD', 'OMNI', 'ONELIFECAP', 'PURPLEUTED', 'RANEHOLDIN', 'RUBICON', 'SASKEN', 'SHREEJISPG', 'SSFL', 'VENUSREM']

print("=== DIAGNOSING DIFFERENCES BETWEEN BACKTESTER UI & TRADESIGNAL PROJECT ===")

# Load tradesignal backtest results CSV
ts_csv = r"C:\Users\Yug\Desktop\tradesignal\rsi_backtest_results_1506_to_2807.csv"
if os.path.exists(ts_csv):
    df_ts_res = pd.read_csv(ts_csv)
    print("\nTradesignal Result CSV Trades:")
    print(df_ts_res[['symbol', 'signal_date', 'entry_date', 'entry_price', 'exit_reason', 'pnl_pct']].to_string())

# Load RSI backtester comparison results JSON
json_path = r"c:\Users\Yug\Desktop\rsi\tradesignal_comparison_results.json"
import json
with open(json_path) as f:
    rsi_json = json.load(f)

print(f"\nRSI Backtester JSON total signals: {len(rsi_json['signals'])}")

# Check why AEGISLOG, BIKEWO, HONASA, RUBICON were in tradesignal vs RSI JSON
print("\n--- DETAILED CHECK FOR TRADESIGNAL-ONLY TRADES (AEGISLOG, BIKEWO, HONASA, RUBICON) ---")
for sym in ['AEGISLOG', 'BIKEWO', 'HONASA', 'RUBICON']:
    matching_json = [s for s in rsi_json['signals'] if s['company'] == sym]
    print(f"\nSymbol: {sym}")
    if not matching_json:
        print("  -> Not in RSI JSON at all!")
    else:
        for s in matching_json:
            print(f"  -> Found in RSI JSON: signal_date={s['signal_date'][:10]}, RSI_LTF={s.get('rsi')}, RSI_HTF={s.get('rsi_HTF')}, ADX={s.get('adx')}, Range={(s['signal_high']-s['signal_low'])/s['signal_low']*100:.1f}%")
