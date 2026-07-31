import pandas as pd
from datetime import datetime
import sys
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings
loader = MarketDataLoader('c:/Users/Yug/Desktop/rsi/data')
for sym in ['MODISONLTD', 'ONELIFECAP']:
    df = loader.resolve_timeframe_path(sym, 'daily')
    df = loader._read_csv(df)
    settings = StrategySettings()
    strategy = RSISupertrendStrategy(settings)
    sigs = strategy.generate_signals(df)
    mask = (sigs['datetime'] >= '2026-06-15') & (sigs['datetime'] <= '2026-07-28') & (sigs['signal'] != 0)
    print(f'{sym} signals:', len(sigs[mask]))
    if len(sigs[mask]) == 0:
        print(f'{sym} total bars:', len(df))
        print(f'{sym} EMA isna:', sigs['ema_200'].isna().sum(), '/', len(sigs))
