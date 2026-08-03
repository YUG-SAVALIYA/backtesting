import pandas as pd
import sys
import json
import logging
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

logging.disable(logging.CRITICAL)

loader = MarketDataLoader('c:/Users/Yug/Desktop/rsi/data')

# Load all companies
mega_df = pd.read_csv('c:/Users/Yug/Desktop/rsi/data/companies_1yr_daily_candles.csv')
symbols = mega_df['symbol'].unique()

all_trades = []

settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    htf_supertrend_period=14,
    htf_supertrend_multiplier=1.0,
    min_adx=26.0,
    min_candle_range=3.0,
    max_candle_range=9.0,
    entry_offset_pct=3.0,
    entry_lookahead_bars=1,
    max_stoploss_pct=5.0
)

strategy = RSISupertrendStrategy(settings)

start = pd.to_datetime('2026-06-15')
end = pd.to_datetime('2026-07-28')

for sym in symbols:
    try:
        htf = loader._read_csv(loader.resolve_timeframe_path(sym, 'Week'))
        ltf = loader._read_csv(loader.resolve_timeframe_path(sym, 'Day'))
        execution = loader._read_csv(loader.resolve_timeframe_path(sym, '5m'))
        
        signal_df, execution_df = strategy.prepare_frames(ltf, execution, htf_df=htf)
        trades = strategy.generate_signals(sym, signal_df, execution_df, target_level=20.0)
        
        for t in trades:
            if start <= pd.to_datetime(t.signal_time) <= end:
                all_trades.append({
                    'symbol': sym,
                    'signal_time': str(t.signal_time),
                    'entry_price': getattr(t, 'entry_price', None), # For new version, it might be None
                    'modes': t.modes
                })
    except Exception as e:
        pass # Ignore missing files

print(f"Total trades: {len(all_trades)}")
with open('c:/Users/Yug/Desktop/rsi/backtester_all_trades.json', 'w') as f:
    json.dump(all_trades, f, indent=2)
