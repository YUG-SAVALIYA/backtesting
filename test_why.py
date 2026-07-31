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
    try:
        htf = loader._read_csv(loader.resolve_timeframe_path(sym, req.htf))
        ltf = loader._read_csv(loader.resolve_timeframe_path(sym, req.ltf))
        print(f'{sym}: loaded HTF {len(htf)} rows, LTF {len(ltf)} rows')
        
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
        
        max_ltf_rsi = valid_sigs["rsi"].max()
        max_htf_rsi = valid_sigs["rsi_htf"].max()
        ltf_up = valid_sigs["in_uptrend"].sum()
        htf_up = valid_sigs["in_uptrend_htf"].sum()
        
        print(f'  Max LTF RSI: {max_ltf_rsi}')
        print(f'  Max HTF RSI: {max_htf_rsi}')
        print(f'  LTF Uptrend days: {ltf_up} out of {len(valid_sigs)}')
        print(f'  HTF Uptrend days: {htf_up} out of {len(valid_sigs)}')
        
    except Exception as e:
        print(f'Error on {sym}: {e}')
