import sys
import pandas as pd
sys.path.append('c:/Users/Yug/Desktop/rsi/src')
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

loader = MarketDataLoader('c:/Users/Yug/Desktop/rsi/data')

for sym in ['MODISONLTD', 'ONELIFECAP', 'CONSOFINVT']:
    try:
        htf = loader._read_csv(loader.resolve_timeframe_path(sym, 'Week'))
        ltf = loader._read_csv(loader.resolve_timeframe_path(sym, 'Day'))
        execution = loader._read_csv(loader.resolve_timeframe_path(sym, '5m'))
        
        settings = StrategySettings(
            rsi_period=14,
            rsi_min=65.0,
            rsi_max=90.0,
            htf_rsi_period=14,
            htf_rsi_min=65.0, # Exact tradesignal: Weekly > 65
            htf_rsi_max=85.0,
            supertrend_period=21,
            supertrend_multiplier=1.5,
            htf_supertrend_period=14,
            htf_supertrend_multiplier=1.0,
            min_adx=26.0,
            min_candle_range=3.0,
            max_candle_range=9.0,
            entry_offset_pct=3.0, # 1.03 * signal_high
            entry_lookahead_bars=1,
            max_stoploss_pct=5.0
        )
        strategy = RSISupertrendStrategy(settings)
        signal_df, execution_df = strategy.prepare_frames(ltf, execution, htf_df=htf)
        
        start = pd.to_datetime('2026-06-15')
        end = pd.to_datetime('2026-07-28')
        
        trades = strategy.generate_signals(sym, signal_df, execution_df, target_level=17.0)
        valid_trades = [t for t in trades if start <= pd.to_datetime(t.signal_time) <= end]
        
        print(f'\n--- {sym} ---')
        print(f'Total trades in period (with tradesignal params): {len(valid_trades)}')
        for t in valid_trades:
            # We must parse the gap_up_modes or standard fields.
            if hasattr(t, 'trade_result') and t.trade_result:
                tr = t.trade_result
                print(f"  Signal: {t.signal_time} | Entry: {t.entry_price} @ {t.entry_time} | Exit: {tr.exit_price} (Reason: {tr.exit_reason}) | PNL: {tr.pnl_pct:.2f}%")
            else:
                print(f"  Signal: {t.signal_time} | Entry: {t.entry_price} @ {t.entry_time} | Status: OPEN")
                
    except Exception as e:
        print(f'Error on {sym}: {e}')
