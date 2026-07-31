import sys
import pandas as pd
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

loader = MarketDataLoader('c:/Users/Yug/Desktop/rsi/data')
htf = loader._read_csv(loader.resolve_timeframe_path('ONELIFECAP', 'Week'))
ltf = loader._read_csv(loader.resolve_timeframe_path('ONELIFECAP', 'Day'))
execution = loader._read_csv(loader.resolve_timeframe_path('ONELIFECAP', '5m'))

settings = StrategySettings(
    rsi_period=14, rsi_min=65.0, rsi_max=90.0,
    htf_rsi_period=14, htf_rsi_min=60.0, htf_rsi_max=85.0,
    supertrend_period=21, supertrend_multiplier=1.5,
    htf_supertrend_period=14, htf_supertrend_multiplier=1.0,
    min_adx=26.0, min_candle_range=3.0, max_candle_range=9.0,
    entry_offset_pct=3.0, entry_lookahead_bars=1, max_stoploss_pct=5.0
)
strategy = RSISupertrendStrategy(settings)
signal_df, execution_df = strategy.prepare_frames(ltf, execution, htf_df=htf)

start = pd.to_datetime('2026-06-16')
idx = signal_df[signal_df['datetime'] == start].index[0]
row = signal_df.iloc[idx]
print('Signal row on 16th:')
print(f"High: {row['high']}, Low: {row['low']}, Entry Level: {row['high'] * 1.03}")

entry_price, entry_time, gap_up, pullback = strategy._find_entry(
    signal_df, idx, execution_df, row['low'], row['high'] * 1.03
)
print(f'Entry: {entry_price} at {entry_time}')
