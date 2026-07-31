import os
import sys
import pandas as pd
import json

backend_path = r"c:\Users\Yug\Desktop\rsi\src"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"
data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"

df_daily_all = pd.read_csv(daily_csv_path)
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    min_adx=26.0,
    min_candle_range=3.0,
    max_candle_range=8.0,
    max_stoploss_pct=0.05,
    min_close_lf_pct=0.0,
    trade_management_enabled=True,
    trade_management_book_pct=50.0,
    trade_management_trigger_pct=10.0
)

strategy = RSISupertrendStrategy(settings)

test_syms = ['AEGISLOG', 'FCL', 'FILATEX', 'RUBICON']

print("=== TESTING BACKTESTER WITH DAILY CANDLE FALLBACK FOR MISSING 5M DATA ===")

for sym in test_syms:
    df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
    if df_sym.empty:
        continue
        
    df_idx = df_sym.set_index('datetime')
    htf_df = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    five_m_file = os.path.join(data_5m_dir, f"{sym}_5m.csv")
    if os.path.exists(five_m_file):
        try:
            exec_df = pd.read_csv(five_m_file)
            exec_df['datetime'] = pd.to_datetime(exec_df['datetime'])
        except Exception:
            exec_df = df_sym.copy()
    else:
        exec_df = df_sym.copy()
        
    sig_df, exec_df_p = strategy.prepare_frames(df_sym, exec_df, htf_df)
    sigs = strategy.generate_signals(sym, sig_df, exec_df_p, target_level=17)
    
    valid_sigs = [s for s in sigs if "2026-06-15" <= str(s.signal_time)[:10] <= "2026-07-28"]
    print(f"\nSymbol {sym}: Generated {len(valid_sigs)} signals with Daily Fallback")
    for s in valid_sigs:
        print(f"  -> Signal Date: {str(s.signal_time)[:10]} | Entry: {s.entry} | Exit Reason: {s.exit_reason}")
