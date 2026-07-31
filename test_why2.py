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
        htf_supertrend_multiplier=req.htf_supertrend_multiplier
    )
    strategy = RSISupertrendStrategy(settings)
    signal_df, _ = strategy.prepare_frames(ltf, ltf, htf_df=htf)
    
    start = pd.to_datetime('2026-06-15')
    end = pd.to_datetime('2026-07-28')
    mask = (signal_df['datetime'] >= start) & (signal_df['datetime'] <= end)
    valid_sigs = signal_df[mask]
    
    cond1 = (valid_sigs["rsi"] >= req.rsi_ltf_min) & (valid_sigs["rsi"] <= req.rsi_ltf_max)
    cond2 = (valid_sigs["rsi_htf"] >= req.rsi_htf_min) & (valid_sigs["rsi_htf"] <= req.rsi_htf_max)
    cond3 = valid_sigs["in_uptrend"] == True
    cond4 = valid_sigs["in_uptrend_htf"] == True
    
    combined = cond1 & cond2 & cond3 & cond4
    print(f'{sym} valid base signals: {combined.sum()}')
    if combined.sum() == 0:
        print(f'  Why {sym} failed:')
        print(f'  Days with LTF RSI in range: {cond1.sum()}')
        print(f'  Days with HTF RSI in range: {cond2.sum()}')
        print(f'  Days with LTF Supertrend Green: {cond3.sum()}')
        print(f'  Days with HTF Supertrend Green: {cond4.sum()}')
        print(f'  Days with BOTH RSI in range: {(cond1 & cond2).sum()}')
