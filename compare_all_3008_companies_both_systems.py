import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, time
from concurrent.futures import ProcessPoolExecutor

# Insert paths for both systems
rsi_path = r"c:\Users\Yug\Desktop\rsi\src"
if rsi_path not in sys.path:
    sys.path.insert(0, rsi_path)

backend_path = r"c:\Users\Yug\Desktop\tradesignal\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy as BacktesterStrategy, StrategySettings as BacktesterSettings
from services.rsi.rsi_strategy import RSISupertrendStrategy as LiveStrategy, StrategySettings as LiveSettings

data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"
daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"

# Configure Settings EXACTLY matching Image 1 & Image 2:
# Target = 17%, SL = 5%, Book 50% at 10%, LTF 65-90, HTF 60-85, ADX >= 26, Range 3-8%
# Pre-Final Confirmation: Max High LF > 3%, Close LF > 0%
backtester_settings = BacktesterSettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    min_adx=26.0,
    min_candle_range=3.0,
    max_candle_range=8.0,
    max_stoploss_pct=0.05,
    min_close_lf_pct=0.0,
    trade_management_enabled=True,
    trade_management_book_pct=50.0,
    trade_management_trigger_pct=10.0
)

live_settings = LiveSettings(
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
    signal_candle_range_max_pct=8.0,
    max_stoploss_pct=0.05
)

bt_strat = BacktesterStrategy(backtester_settings)
live_strat = LiveStrategy(live_settings)

def process_company(args):
    sym, df_sym = args
    clean_sym = sym.replace(".NS", "").strip().upper()
    if len(df_sym) < 50:
        return [], []
        
    df_sym = df_sym.sort_values('datetime').reset_index(drop=True)
    df_idx = df_sym.set_index('datetime')
    htf_df = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    five_m_file = os.path.join(data_5m_dir, f"{clean_sym}_5m.csv")
    df_5m = None
    if os.path.exists(five_m_file):
        try:
            df_5m = pd.read_csv(five_m_file)
            df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
            df_5m = df_5m.sort_values('dt').reset_index(drop=True)
        except Exception:
            df_5m = None

    # -------------------------------------------------------------
    # RUN 1: BACKTESTER SYSTEM RUN (Target = 17%)
    # -------------------------------------------------------------
    bt_trades = []
    if df_5m is not None:
        exec_df = df_5m.copy().set_index('dt')
        sig_df, exec_df_p = bt_strat.prepare_frames(df_sym.copy(), exec_df, htf_df)
        sigs_bt = bt_strat.generate_signals(clean_sym, sig_df, exec_df_p, target_level=17)
        
        valid_sigs_bt = [s for s in sigs_bt if "2026-06-15" <= str(s.signal_time)[:10] <= "2026-07-28"]
        for s in valid_sigs_bt:
            mode_data = s.gap_up_modes.get("gap_up_sl_target_update", {}) if hasattr(s, 'gap_up_modes') and s.gap_up_modes else s.to_dict()
            bt_trades.append({
                "Symbol": clean_sym,
                "Signal Date": str(s.signal_time)[:10],
                "Entry Date": str(mode_data.get('entry_time', s.entry_time))[:10],
                "Entry Price": round(mode_data.get('new_entry') or mode_data.get('entry') or s.entry, 2),
                "Exit Reason": mode_data.get('exit_type') or s.exit_reason,
                "Exit Price": round(mode_data.get('exit_price') or s.exit_price or 0, 2),
                "PnL (%)": round(mode_data.get('trade_management_weighted_return_pct') or s.trade_management_weighted_return_pct or 0, 2)
            })

    # -------------------------------------------------------------
    # RUN 2: LIVE SYSTEM RUN (tradesignal, Target = 17%)
    # -------------------------------------------------------------
    live_trades = []
    sig_df_live, exec_df_live = live_strat.prepare_frames(df_sym.copy(), df_sym.copy(), htf_df)
    sigs_live = live_strat.generate_signals(clean_sym, sig_df_live, exec_df_live, target_level=17.0)
    valid_sigs_live = [s for s in sigs_live if "2026-06-15" <= pd.to_datetime(s.entry_time).strftime("%Y-%m-%d") <= "2026-07-28"]
    
    for sig in valid_sigs_live:
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
        
        if df_5m is not None:
            day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date_str].reset_index(drop=True)
            if not day1_5m.empty:
                for idx, row in day1_5m.iterrows():
                    bar_time = row['dt'].time()
                    if bar_time <= time(15, 20):
                        if row['high'] >= trigger_price:
                            is_triggered = True
                    if bar_time == time(15, 20):
                        entry_bar_price = row['close']
                        break
                if entry_bar_price is None and not day1_5m.empty:
                    entry_bar_price = day1_5m['close'].iloc[-1]
                    if day1_5m['high'].max() >= trigger_price:
                        is_triggered = True
                        
        if entry_bar_price is None:
            day1_high = entry_day['high']
            if day1_high >= trigger_price:
                is_triggered = True
            entry_bar_price = entry_day['close']
            
        if not is_triggered or entry_bar_price <= sig_high:
            continue
            
        entry_price = entry_bar_price
        target = round(entry_price * 1.17, 3) # Target = 17%
        stop_loss = round(max(sig_low, entry_price * 0.95), 3)
        
        exit_reason = None
        exit_price = None
        exit_time = None
        partial_taken = False
        curr_sl = stop_loss
        
        post_entry_daily = df_sym[df_sym['datetime'] >= entry_day['datetime']].reset_index(drop=True)
        
        for idx, d_row in post_entry_daily.iterrows():
            curr_date_str = pd.to_datetime(d_row['datetime']).strftime("%Y-%m-%d")
            
            if not partial_taken and d_row['high'] >= entry_price * 1.10:
                partial_taken = True
                curr_sl = entry_price
                
            if d_row['low'] <= curr_sl:
                exit_reason = "Stoploss Hit" if not partial_taken else "Trade Mgmt Breakeven"
                exit_price = curr_sl
                exit_time = curr_date_str
                break
                
            if d_row['high'] >= target:
                exit_reason = "Target Hit"
                exit_price = target
                exit_time = curr_date_str
                break
                
            if idx >= 20:
                exit_reason = "Time Limit"
                exit_price = d_row['close']
                exit_time = curr_date_str
                break
                
        if exit_reason is None:
            last_row = post_entry_daily.iloc[-1]
            exit_reason = "Time Limit"
            exit_price = last_row['close']
            exit_time = str(last_row['datetime'])[:10]
            
        if partial_taken:
            pnl_pct = 0.5 * 10.0 + 0.5 * (((exit_price - entry_price) / entry_price) * 100.0)
        else:
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
            
        live_trades.append({
            "Symbol": clean_sym,
            "Signal Date": sig_date_str,
            "Entry Date": entry_date_str,
            "Entry Price": round(entry_price, 2),
            "Exit Reason": exit_reason,
            "Exit Price": round(exit_price, 2),
            "PnL (%)": round(pnl_pct, 2)
        })
        
    return bt_trades, live_trades

if __name__ == '__main__':
    print("Loading daily candles for ALL 3008 companies...")
    df_daily_all = pd.read_csv(daily_csv_path)
    if 'date' in df_daily_all.columns:
        df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
    df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

    grouped = list(df_daily_all.groupby('symbol'))
    print(f"Loaded {len(grouped)} company datasets. Running Backtest vs Live comparison...")

    all_bt_trades = []
    all_live_trades = []
    
    with ProcessPoolExecutor() as executor:
        results = executor.map(process_company, grouped)
        for bt, live in results:
            all_bt_trades.extend(bt)
            all_live_trades.extend(live)

    df_bt = pd.DataFrame(all_bt_trades)
    df_live = pd.DataFrame(all_live_trades)
    
    print("\n================ FULL SIDE-BY-SIDE MATCH RESULTS (EXACT IMAGE PARAMETERS) ================")
    print(f"Total Trades in Backtester System: {len(df_bt)}")
    print(f"Total Trades in Live System: {len(df_live)}")

    merged = pd.merge(df_bt, df_live, on=['Symbol', 'Signal Date'], how='outer', suffixes=('_BACKTESTER', '_LIVE'))

    print("\n--- DETAILED SIDE-BY-SIDE TABLE ---")
    print(merged.to_string(index=False))

    exact_matches = 0
    for idx, row in merged.iterrows():
        b_entry = row.get('Entry Price_BACKTESTER')
        l_entry = row.get('Entry Price_LIVE')
        
        if pd.notna(b_entry) and pd.notna(l_entry) and abs(b_entry - l_entry) < 0.01:
            exact_matches += 1

    print(f"\n================ SUMMARY RESULTS ================")
    print(f"Total Unique Signal Matches: {exact_matches}")
    print(f"Match Percentage: {(exact_matches / len(merged)) * 100.0 if len(merged) > 0 else 0:.2f}%")
