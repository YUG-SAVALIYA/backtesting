import json, time
from rsi_supertrend_backtester.core.backtest_worker import process_single_company_worker
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

with open('config.json', 'r') as f:
    cfg = json.load(f)

settings = StrategySettings()
strategy = RSISupertrendStrategy(settings)
loader = MarketDataLoader(cfg['data_dir'])

signal_df, execution_df, htf_df = loader.load_symbol_frames('AUBANK','daily','5min','weekly')
signal_df, execution_df = strategy.prepare_frames(signal_df, execution_df, htf_df)
direct_signals = strategy.generate_signals('AUBANK', signal_df, execution_df, 17)
print(f"Direct: {len(direct_signals)} signals")
if direct_signals:
    s = direct_signals[0]
    print(f"  Signal 0: entry={s.entry}, target={s.target}, stoploss={s.stoploss}, target_hit={s.target_hit}")

# Worker
result = process_single_company_worker({
    'company': 'AUBANK',
    'data_dir': 'F:/Data',
    'ltf': 'daily', 'execution_timeframe_file_suffix': '5min', 'htf': 'weekly',
    'target_level': 17,
    'start_dt': '2021-01-01', 'end_dt': '2025-12-31', 'end_exclusive': None,
    'entry_lookahead_variants': [1],
    'settings': {
        'rsi_period': 21, 'rsi_min': 50, 'rsi_max': 90,
        'htf_rsi_period': 21, 'htf_rsi_min': 65, 'htf_rsi_max': 85,
        'supertrend_period': 21, 'supertrend_multiplier': 1.5,
        'htf_supertrend_period': 14, 'htf_supertrend_multiplier': 1.0,
        'max_stoploss_pct': 0.03, 'stoploss_mode': 'signal_candle_low',
        'look_forward_limit': 1575, 'target_mode': 'fixed',
        'atr_multiplier': 2.0, 'entry_offset_pct': 0.0,
        'trade_management_enabled': True,
        'trade_management_book_pct': 50, 'trade_management_trigger_pct': 5,
        'trade_management_targets': [],
    },
})
worker_sigs = result['signals_by_bars']['1']
err = result["error"]
print(f"Worker: {len(worker_sigs)} signals, err={err}")
if worker_sigs:
    ws = worker_sigs[0]
    print(f"  Signal 0: entry={ws['entry']}, target={ws['target']}, stoploss={ws['stoploss']}, target_hit={ws['target_hit']}")
