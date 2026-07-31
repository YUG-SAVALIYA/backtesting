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
        htf_rsi_min=60.0,
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
    
    print(f'\n--- {sym} ---')
    cond_st = valid_sigs['in_uptrend'] == True
    cond_st_change = (valid_sigs['in_uptrend'].shift(1) == False) & cond_st
    cond_rsi = (valid_sigs['rsi'] >= 65) & (valid_sigs['rsi'] <= 90)
    cond_htf_rsi = (valid_sigs['rsi_htf'] > 65) & (valid_sigs['rsi_htf'] < 85)
    
    has_adx = 'adx' in valid_sigs.columns
    if has_adx:
        max_adx = valid_sigs["adx"].max()
        print(f'ADX found. Max ADX: {max_adx}')
    
    print(f'Days ST Green: {cond_st.sum()}')
    print(f'Days ST flipped to Green: {cond_st_change.sum()}')
    print(f'Days RSI daily (65-90): {cond_rsi.sum()}')
    print(f'Days RSI weekly (65-85): {cond_htf_rsi.sum()}')
    
    print('Candle Ranges where ST is green:')
    print(valid_sigs[cond_st]['candle_range'].describe())
