import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, time

backend_path = r"c:\Users\Yug\Desktop\tradesignal\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from services.rsi.rsi_strategy import RSISupertrendStrategy, StrategySettings

data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"
daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"

df_daily_all = pd.read_csv(daily_csv_path)
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

# Configure Strategy Settings to match optimal UI parameters:
settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=65.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    adx_period=14,
    adx_min=26.0,
    signal_candle_range_min_pct=3.0,
    signal_candle_range_max_pct=8.0,
    max_stoploss_pct=0.05
)

strategy = RSISupertrendStrategy(settings)
symbols = df_daily_all['symbol'].unique()

trades = []

for sym in symbols:
    clean_sym = sym.replace(".NS", "").strip().upper()
    df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
    if len(df_sym) < 50:
        continue
        
    df_idx = df_sym.set_index('datetime')
    htf_df = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    sig_df, exec_df = strategy.prepare_frames(df_sym.copy(), df_sym.copy(), htf_df)
    sigs = strategy.generate_signals(sym, sig_df, exec_df, target_level=20.0)
    
    valid_sigs = [s for s in sigs if "2026-06-15" <= pd.to_datetime(s.entry_time).strftime("%Y-%m-%d") <= "2026-07-28"]
    if not valid_sigs:
        continue
        
    five_m_file = os.path.join(data_5m_dir, f"{clean_sym}_5m.csv")
    df_5m = None
    if os.path.exists(five_m_file):
        try:
            df_5m = pd.read_csv(five_m_file)
            df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
            df_5m = df_5m.sort_values('dt').reset_index(drop=True)
        except Exception:
            df_5m = None

    for sig in valid_sigs:
        sig_dt = pd.to_datetime(sig.entry_time)
        sig_date_str = sig_dt.strftime("%Y-%m-%d")
        
        future_days = df_sym[df_sym['datetime'] > sig_dt]
        if future_days.empty:
            continue
        
        entry_day = future_days.iloc[0]
        entry_date_str = pd.to_datetime(entry_day['datetime']).strftime("%Y-%m-%d")
        
        sig_high = sig.signal_high
        sig_low = sig.signal_low
        trigger_price = round(sig_high * 1.03, 2)
        
        entry_bar_price = None
        is_triggered = False
        is_invalidated = False
        
        if df_5m is not None:
            day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date_str].reset_index(drop=True)
            if not day1_5m.empty:
                for idx, row in day1_5m.iterrows():
                    bar_time = row['dt'].time()
                    if bar_time <= time(15, 20):
                        if row['low'] <= sig_low:
                            is_invalidated = True
                            break
                        if row['high'] >= trigger_price:
                            is_triggered = True
                    if bar_time == time(15, 20):
                        entry_bar_price = row['close']
                        break
                        
                # If 15:20 bar was missing in 5m CSV, fallback to last available bar of the day
                if entry_bar_price is None and not day1_5m.empty:
                    entry_bar_price = day1_5m['close'].iloc[-1]
                    if day1_5m['high'].max() >= trigger_price:
                        is_triggered = True
                        
        # If no 5m data at all, fallback to daily candle values
        if entry_bar_price is None:
            day1_high = entry_day['high']
            day1_low = entry_day['low']
            if day1_low <= sig_low:
                is_invalidated = True
            if day1_high >= trigger_price:
                is_triggered = True
            entry_bar_price = entry_day['close']
            
        if is_invalidated or not is_triggered or entry_bar_price <= sig_high:
            continue
            
        entry_price = entry_bar_price
        max_sl_price = round(entry_price * 0.95, 2)
        stop_loss = max(sig_low, max_sl_price)
        target = round(entry_price * 1.20, 2)
        
        # Trade tracking
        exit_reason = None
        exit_price = None
        exit_time = None
        partial_taken = False
        curr_sl = stop_loss
        
        post_entry_daily = df_sym[df_sym['datetime'] >= entry_day['datetime']].reset_index(drop=True)
        
        if df_5m is not None:
            remaining_5m = df_5m[df_5m['dt'] >= pd.Timestamp(f"{entry_date_str} 15:20:00")].reset_index(drop=True)
            if not remaining_5m.empty:
                for idx, row in remaining_5m.iterrows():
                    curr_dt = row['dt']
                    curr_date_str = curr_dt.strftime("%Y-%m-%d")
                    curr_time = curr_dt.time()
                    
                    if not partial_taken and row['high'] >= entry_price * 1.10:
                        partial_taken = True
                        curr_sl = entry_price
                        
                    if row['low'] <= curr_sl:
                        exit_reason = "STOPLOSS"
                        exit_price = min(curr_sl, row['open'])
                        exit_time = str(curr_dt)
                        break
                        
                    if row['high'] >= target:
                        exit_reason = "TARGET"
                        exit_price = target
                        exit_time = str(curr_dt)
                        break
                        
                    if curr_time == time(15, 20):
                        daily_matches = post_entry_daily[post_entry_daily['datetime'].dt.strftime("%Y-%m-%d") == curr_date_str]
                        if not daily_matches.empty:
                            d_idx = daily_matches.index[0]
                            if d_idx >= 21:
                                exit_reason = "TIME_LIMIT"
                                exit_price = row['close']
                                exit_time = str(curr_dt)
                                break
                                
                            daily_row_idx = df_sym[df_sym['datetime'].dt.strftime("%Y-%m-%d") == curr_date_str].index
                            if not daily_row_idx.empty:
                                r_idx = daily_row_idx[0]
                                if sig_df.loc[r_idx, 'supertrend_dir'] == -1:
                                    exit_reason = "SUPERTREND_RED"
                                    exit_price = row['close']
                                    exit_time = str(curr_dt)
                                    break

        # Fallback to daily tracking if exit_reason is None
        if exit_reason is None:
            for idx, d_row in post_entry_daily.iterrows():
                curr_date_str = pd.to_datetime(d_row['datetime']).strftime("%Y-%m-%d")
                if not partial_taken and d_row['high'] >= entry_price * 1.10:
                    partial_taken = True
                    curr_sl = entry_price
                if d_row['low'] <= curr_sl:
                    exit_reason = "STOPLOSS"
                    exit_price = min(curr_sl, d_row['open'])
                    exit_time = curr_date_str
                    break
                if d_row['high'] >= target:
                    exit_reason = "TARGET"
                    exit_price = target
                    exit_time = curr_date_str
                    break
                if idx >= 21:
                    exit_reason = "TIME_LIMIT"
                    exit_price = d_row['close']
                    exit_time = curr_date_str
                    break
                    
        if exit_reason is None:
            last_row = post_entry_daily.iloc[-1]
            exit_reason = "OPEN"
            exit_price = last_row['close']
            exit_time = str(last_row['datetime'])[:10]
            
        if partial_taken:
            pnl_pct = 0.5 * 10.0 + 0.5 * (((exit_price - entry_price) / entry_price) * 100.0)
        else:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
            
        trades.append({
            "symbol": clean_sym,
            "signal_date": sig_date_str,
            "entry_date": entry_date_str,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "target": target,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "partial_10pct_taken": partial_taken,
            "pnl_pct": round(pnl_pct, 2)
        })

df_res = pd.DataFrame(trades)
print("=== TRADESIGNAL WITH DATA GAP FALLBACK ===")
print(df_res[['symbol', 'signal_date', 'entry_date', 'entry_price', 'exit_reason', 'partial_10pct_taken', 'pnl_pct']].to_string())
