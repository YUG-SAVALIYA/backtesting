import json
from rsi_supertrend_backtester.core.backtest_worker import process_single_company_worker

result = process_single_company_worker({
    'company': 'AUBANK', 'data_dir': 'F:/Data',
    'ltf': 'daily', 'execution_timeframe_file_suffix': '5min', 'htf': 'weekly',
    'target_level': 17,
    'start_dt': '2019-01-01', 'end_dt': '2026-12-31', 'end_exclusive': None,
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
sigs = result['signals_by_bars']['1']
print(f"Signals: {len(sigs)}, error: {result['error']}")
for i, s in enumerate(sigs):
    print(f"  [{i}] entry={s['entry']}, target={s['target']}, stoploss={s['stoploss']}, target_hit={s['target_hit']}, stoploss_hit={s['stoploss_hit']}")
