import os
import pandas as pd
import json

data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"

with open('c:/Users/Yug/Desktop/rsi/tradesignal_comparison_results.json') as f:
    rsi_json = json.load(f)

ui_trades = ['APEXECO', 'FCL', 'KAMDHENU', 'KERNEX', 'ONELIFECAP', 'SHREEJISPG', 'SSFL', 'VENUSREM']

print("=== CHECKING WHY UI TRADES DIFFER FROM 5MIN TRADESIGNAL TRADES ===")

for sym in ui_trades:
    five_m_file = os.path.join(data_5m_dir, f"{sym}_5m.csv")
    exists = os.path.exists(five_m_file)
    print(f"\nSymbol: {sym} | 5m File Exists: {exists}")
    
    matching_json = [s for s in rsi_json['signals'] if s['company'] == sym]
    if matching_json:
        for s in matching_json:
            sig_date = s['signal_date'][:10]
            close_replay = s.get('close_lf_replay') or {}
            entry_date = (close_replay.get('entry_time') or '')[:10]
            sig_high = s['signal_high']
            sig_low = s['signal_low']
            print(f"  Signal Date: {sig_date} | Entry Date: {entry_date} | Signal High: {sig_high} | Signal Low: {sig_low}")
            print(f"  UI Replay Entry: {close_replay.get('entry')} | ExitReason: {close_replay.get('exit_reason')} | ExitPrice: {close_replay.get('exit_price')}")
            
            if exists:
                df_5m = pd.read_csv(five_m_file)
                df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
                day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date].reset_index(drop=True)
                if day1_5m.empty:
                    print(f"  -> REASON FOR DIFFERENCE: No 5-minute intraday data found for Day 1 ({entry_date})!")
                else:
                    bar_320 = day1_5m[day1_5m['dt'].dt.time == pd.to_datetime("15:20").time()]
                    bar_320_close = bar_320.iloc[0]['close'] if not bar_320.empty else None
                    max_h_5m = day1_5m['high'].max()
                    min_l_5m = day1_5m['low'].min()
                    dip_below_low = any(day1_5m['low'] <= sig_low)
                    
                    print(f"  5m Day 1 High: {max_h_5m} (target 3%: {sig_high * 1.03:.2f}) | 3:20 Close: {bar_320_close} | Min Low: {min_l_5m} | Dip Below Sig Low: {dip_below_low}")
                    
                    if not exists or day1_5m.empty:
                        print("  -> REASON: Missing 5m data!")
                    elif dip_below_low:
                        print(f"  -> REASON FOR DIFFERENCE IN TRADESIGNAL: Intraday price dipped below Signal Low ({sig_low}) on Day 1! Tradesignal rejects entry on intraday dip, but Daily Backtester UI ignores pre-3:20PM dips.")
                    elif max_h_5m < sig_high * 1.03:
                        print(f"  -> REASON: Intraday 5m high ({max_h_5m}) did not reach 3% trigger ({sig_high * 1.03:.2f}).")
                    elif bar_320_close <= sig_high:
                        print(f"  -> REASON: 3:20 PM close ({bar_320_close}) was below Signal High ({sig_high}).")
