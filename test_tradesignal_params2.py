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
    htf = loader._read_csv(loader.resolve_timeframe_path(sym, req.htf))
    ltf = loader._read_csv(loader.resolve_timeframe_path(sym, req.ltf))
    execution = loader._read_csv(loader.resolve_timeframe_path(sym, '5m'))
    
    settings = StrategySettings(
        rsi_period=14,
        rsi_min=65.0,
        rsi_max=90.0,
        htf_rsi_period=14,
        htf_rsi_min=65.0, # Rule 1: Weekly RSI > 65
        htf_rsi_max=85.0,
        supertrend_period=21,
        supertrend_multiplier=1.5,
        htf_supertrend_period=14,
        htf_supertrend_multiplier=1.0,
        min_adx=26.0, # Hidden ADX Filter
        max_candle_range=10.0, # Candle Size Max
        entry_offset_pct=0.0, # Not specified in rules to change, UI used 0.0
        entry_lookahead_bars=1,
        max_stoploss_pct=5.0
    )
    strategy = RSISupertrendStrategy(settings)
    signal_df, execution_df = strategy.prepare_frames(ltf, execution, htf_df=htf)
    
    start = pd.to_datetime('2026-06-15')
    end = pd.to_datetime('2026-07-28')
    
    trades = strategy.generate_signals(sym, signal_df, execution_df, target_level=17.0) # Target Percentage: 17%
    valid_trades = [t for t in trades if start <= pd.to_datetime(t.signal_time) <= end]
    
    print(f'\n--- {sym} ---')
    print(f'Total trades in period: {len(valid_trades)}')

