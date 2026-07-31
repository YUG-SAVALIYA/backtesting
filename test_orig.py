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
        rsi_period=req.rsi_ltf_period,
        rsi_min=req.rsi_ltf_min,
        rsi_max=req.rsi_ltf_max,
        htf_rsi_period=req.rsi_htf_period,
        htf_rsi_min=req.rsi_htf_min,
        htf_rsi_max=req.rsi_htf_max,
        supertrend_period=req.supertrend_period,
        supertrend_multiplier=req.supertrend_multiplier,
        htf_supertrend_period=req.htf_supertrend_period,
        htf_supertrend_multiplier=req.htf_supertrend_multiplier,
        entry_offset_pct=req.entry_offset_pct,
        entry_lookahead_bars=req.entry_lookahead_bars,
        max_stoploss_pct=req.max_stoploss_pct
    )
    strategy = RSISupertrendStrategy(settings)
    signal_df, execution_df = strategy.prepare_frames(ltf, execution, htf_df=htf)
    
    start = pd.to_datetime('2026-06-15')
    end = pd.to_datetime('2026-07-28')
    
    trades = strategy.generate_signals(sym, signal_df, execution_df, target_level=req.target_level)
    valid_trades = [t for t in trades if start <= pd.to_datetime(t.signal_time) <= end]
    
    print(f'\n--- {sym} ---')
    print(f'Total trades in period: {len(valid_trades)}')
