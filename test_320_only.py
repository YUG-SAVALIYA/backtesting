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

trades_320_only = []

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
    if not os.path.exists(five_m_file):
        continue
        
    try:
        df_5m = pd.read_csv(five_m_file)
        df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
        df_5m = df_5m.sort_values('dt').reset_index(drop=True)
    except Exception:
        continue

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
        
        # Day 1 3:20 PM Check
        day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date_str].reset_index(drop=True)
        if day1_5m.empty:
            continue
            
        bar_320_day1 = day1_5m[day1_5m['dt'].dt.time == time(15, 20)]
        if bar_320_day1.empty:
            continue
            
        # Check Day 1 max high and 3:20 PM close
        day1_max_high = day1_5m['high'].max()
        day1_min_low = day1_5m['low'].min()
        close_320_day1 = bar_320_day1.iloc[0]['close']
        
        # Pre-final 3% high check & close check
        if day1_max_high < trigger_price or close_320_day1 <= sig_high:
            continue
            
        entry_price = close_320_day1
        max_sl_price = round(entry_price * 0.95, 2)
        stop_loss = max(sig_low, max_sl_price)
        target = round(entry_price * 1.20, 2)
        
        # Filter only 3:20 PM candles for subsequent days
        all_320_bars = df_5m[(df_5m['dt'] >= pd.Timestamp(f"{entry_date_str} 15:20:00")) & (df_5m['dt'].dt.time == time(15, 20))].reset_index(drop=True)
        
        partial_taken = False
        exit_reason = None
        exit_price = None
        exit_time = None
        curr_sl = stop_loss
        
        post_entry_daily = df_sym[df_sym['datetime'] >= entry_day['datetime']].reset_index(drop=True)
        
        for idx, row in all_320_bars.iterrows():
            curr_dt = row['dt']
            curr_date_str = curr_dt.strftime("%Y-%m-%d")
            
            # Check 10% Partial Profit at 3:20 PM
            if not partial_taken and row['high'] >= entry_price * 1.10:
                partial_taken = True
                curr_sl = entry_price
                
            # Check Stoploss at 3:20 PM
            if row['low'] <= curr_sl:
                exit_reason = "STOPLOSS"
                exit_price = min(curr_sl, row['open'])
                exit_time = str(curr_dt)
                break
                
            # Check Target at 3:20 PM
            if row['high'] >= target:
                exit_reason = "TARGET"
                exit_price = target
                exit_time = str(curr_dt)
                break
                
            # Check Time Limit & Supertrend Red at 3:20 PM
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

        if exit_reason is None and not all_320_bars.empty:
            last_row = all_320_bars.iloc[-1]
            exit_reason = "OPEN"
            exit_price = last_row['close']
            exit_time = str(last_row['dt'])
            
        if partial_taken:
            pnl_pct = 0.5 * 10.0 + 0.5 * (((exit_price - entry_price) / entry_price) * 100.0)
        else:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
            
        trades_320_only.append({
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

df_res = pd.DataFrame(trades_320_only)
print("=== TRADESIGNAL EVALUATED STRICTLY ON 3:20 PM CANDLES ===")
print(df_res[['symbol', 'signal_date', 'entry_date', 'entry_price', 'exit_reason', 'partial_10pct_taken', 'pnl_pct']].to_string())
