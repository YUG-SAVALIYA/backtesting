import os
import sys
import pandas as pd

backend_path = r"c:\Users\Yug\Desktop\rsi\src"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"
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
    min_close_lf_pct=0.0
)

strategy = RSISupertrendStrategy(settings)

sym = 'AEGISLOG'
df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
df_idx = df_sym.set_index('datetime')
htf_df = df_idx.resample('W-FRI').agg({
    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
}).dropna().reset_index()

sig_df, exec_df_p = strategy.prepare_frames(df_sym.copy(), df_sym.copy(), htf_df)
sigs = strategy.generate_signals(sym, sig_df, exec_df_p, target_level=17)

print(f"Total AEGISLOG signals generated: {len(sigs)}")
for s in sigs:
    print(f"  Signal Date: {s.signal_time} | Entry: {s.entry} | Exit Reason: {s.exit_reason}")
