import os
import sys
import json
import pandas as pd

json_path = r"c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-13-38-48.json"
with open(json_path) as f:
    json_data = json.load(f)

json_signals = json_data.get('signals', [])

backend_path = r"c:\Users\Yug\Desktop\tradesignal\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from services.rsi.rsi_strategy import RSISupertrendStrategy, StrategySettings

data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"
daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"

df_daily_all = pd.read_csv(daily_csv_path)
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

# Configure Strategy Settings to MATCH exact UI image:
# Gap-Up + SL/Target Update mode, LTF 65-90, HTF 60-85 (W-FRI), ADX >= 26, Range 3-8%
settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    adx_period=14,
    adx_min=26.0,
    signal_candle_range_min_pct=3.0,
    signal_candle_range_max_pct=8.0,
    max_stoploss_pct=0.05
)

strategy = RSISupertrendStrategy(settings)

print("=== DETAILED COMPARISON OF ALL 19 TRADES IN FILTERED JSON vs TRADESIGNAL ===")

for s in json_signals:
    sym = s.get('company')
    sig_date = str(s.get('signal_date'))[:10]
    entry_date = str(s.get('entry_time'))[:10]
    json_entry = s.get('new_entry') or s.get('entry')
    json_target = s.get('new_target') or s.get('Target')
    json_stoploss = s.get('new_stoploss') or s.get('Stoploss')
    json_exit_reason = s.get('exit_type')
    json_exit_price = s.get('exit_price')
    
    print(f"\n------------------------------------------------------------")
    print(f"Symbol: {sym} | Signal Date: {sig_date} | Entry Date: {entry_date}")
    print(f"  JSON Values -> Entry: {json_entry}, Target: {json_target}, Stoploss: {json_stoploss}, ExitReason: {json_exit_reason}, ExitPrice: {json_exit_price}")
    
    # Check 5m file existence in tradesignal
    five_m_file = os.path.join(data_5m_dir, f"{sym}_5m.csv")
    exists = os.path.exists(five_m_file)
    print(f"  Tradesignal 5m File Exists: {exists}")
    
    if exists:
        df_5m = pd.read_csv(five_m_file)
        df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
        day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date].reset_index(drop=True)
        if day1_5m.empty:
            print(f"  -> DIFFERENCE REASON: 5m file exists, but HAS NO BARS for Day 1 ({entry_date})!")
        else:
            bar_320 = day1_5m[day1_5m['dt'].dt.time == pd.to_datetime("15:20").time()]
            has_320 = not bar_320.empty
            bar_320_close = bar_320.iloc[0]['close'] if has_320 else day1_5m['close'].iloc[-1]
            last_time = day1_5m['dt'].iloc[-1].strftime("%H:%M:%S")
            print(f"  Day 1 5m bars: count={len(day1_5m)}, last_time={last_time}, has_1520={has_320}, 320_close={bar_320_close}")
            if not has_320:
                print(f"  -> DIFFERENCE REASON: 5m file ended early at {last_time} before 3:20 PM! (Tradesignal skipped entry because 15:20 candle was missing).")
