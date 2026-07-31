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
        rsi_min=65.0,
        rsi_max=90.0,
        htf_rsi_period=req.rsi_htf_period,
        htf_rsi_min=65.0,
        htf_rsi_max=85.0,
        supertrend_period=21,
        supertrend_multiplier=1.5,
        htf_supertrend_period=req.htf_supertrend_period,
        htf_supertrend_multiplier=req.htf_supertrend_multiplier
    )
    strategy = RSISupertrendStrategy(settings)
    signal_df, _ = strategy.prepare_frames(ltf, ltf, htf_df=htf)
    
    start = pd.to_datetime('2026-06-15')
    end = pd.to_datetime('2026-07-28')
    mask = (signal_df['datetime'] >= start) & (signal_df['datetime'] <= end)
    valid_sigs = signal_df[mask]
    
    cond_st_change = (valid_sigs['in_uptrend'].shift(1) == False) & (valid_sigs['in_uptrend'] == True)
    
    print(f'\n--- {sym} ---')
    flip_days = valid_sigs[cond_st_change]
    if len(flip_days) == 0:
        print('No ST flip from red to green in this period!')
    else:
        for idx, row in flip_days.iterrows():
            print(f"Date: {row['datetime']}, LTF RSI: {row['rsi']:.2f}, HTF RSI: {row['rsi_htf']:.2f}, ADX: {row['adx']:.2f}, Candle Range: {row['candle_range']:.2f}%")
