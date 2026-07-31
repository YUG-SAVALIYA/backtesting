
import json
import sys
import pandas as pd
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings
from rsi_supertrend_backtester.api import BacktestRequest

req_dict = json.load(open('c:/Users/Yug/Desktop/rsi/last_request.json'))
req = BacktestRequest(**req_dict)
loader = MarketDataLoader('c:/Users/Yug/Desktop/rsi/data')

for sym in ['MODISONLTD', 'ONELIFECAP', 'CONSOFINVT']:
    daily = loader._read_csv(loader.resolve_timeframe_path(sym, req.htf))
    five_min = loader._read_csv(loader.resolve_timeframe_path(sym, req.ltf))
    settings = StrategySettings(**req.dict(exclude={'companies', 'start_date', 'end_date', 'ltf', 'htf'}))
    strategy = RSISupertrendStrategy(settings)
    signals = strategy.generate_signals(daily, five_min, target_level='htf')
    
    start = pd.to_datetime('2026-06-15')
    end = pd.to_datetime('2026-07-28')
    mask = (signals['datetime'] >= start) & (signals['datetime'] <= end)
    print(f'{sym} trades found:', len(signals[mask]))
