import sys
import pandas as pd
import json

backend_path = r"c:\Users\Yug\Desktop\tradesignal\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from services.rsi.rsi_strategy import RSISupertrendStrategy, StrategySettings

json_path = r"c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-13-38-48.json"
daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"

with open(json_path) as f:
    json_data = json.load(f)

df_daily_all = pd.read_csv(daily_csv_path)
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    adx_period=14,
    adx_min=26.0,
    signal_candle_range_min_pct=3.0,
    signal_candle_range_max_pct=8.5,
    max_stoploss_pct=0.05
)

strategy = RSISupertrendStrategy(settings)

for sym in ['CONFIPET', 'GALAPREC', 'KAMDHENU', 'XPROINDIA']:
    print(f"\n================ DIAGNOSING {sym} ================")
    df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
    df_idx = df_sym.set_index('datetime')
    htf_df = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    sig_df, exec_df = strategy.prepare_frames(df_sym.copy(), df_sym.copy(), htf_df)
    sigs = strategy.generate_signals(sym, sig_df, exec_df, target_level=20.0)
    
    valid_sigs = [s for s in sigs if "2026-06-15" <= pd.to_datetime(s.entry_time).strftime("%Y-%m-%d") <= "2026-07-28"]
    print(f"Generated signals in target date range: {len(valid_sigs)}")
    for s in valid_sigs:
        sig_dt = pd.to_datetime(s.entry_time)
        print(f"  Signal Date: {sig_dt.strftime('%Y-%m-%d')} | Dict: {s.__dict__}")
        
        future_days = df_sym[df_sym['datetime'] > sig_dt]
        if not future_days.empty:
            entry_day = future_days.iloc[0]
            d1_high = entry_day['high']
            d1_close = entry_day['close']
            trigger = s.signal_high * 1.03
            high_pass = d1_high >= trigger
            close_pass = d1_close > s.signal_high
            print(f"  Day 1 ({entry_day['datetime'].strftime('%Y-%m-%d')}): High={d1_high} (need >= {trigger:.2f}, pass={high_pass}) | Close={d1_close} (need > {s.signal_high}, pass={close_pass})")
