import json
import pandas as pd
import os

with open('c:/Users/Yug/Desktop/rsi/tradesignal_comparison_results.json') as f:
    rsi_json = json.load(f)

signals = rsi_json['signals']

# Load 5m data directory to test tradesignal rule 1 (pre-3:20pm dip below signal low)
data_5m_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"

print("=== DEEP COMPARISON OF ALL 20 SYMBOLS BETWEEN PROJECTS ===")

symbols_ui = ['APEXECO', 'FCL', 'KAMDHENU', 'KERNEX', 'ONELIFECAP', 'SHREEJISPG', 'SSFL', 'VENUSREM']
symbols_ts = ['AEGISLOG', 'BIKEWO', 'FCL', 'HONASA', 'KERNEX', 'RUBICON', 'SHREEJISPG', 'VENUSREM']

all_symbols = sorted(list(set(symbols_ui + symbols_ts)))

for sym in all_symbols:
    matching = [s for s in signals if s['company'] == sym]
    print(f"\n================ Symbol: {sym} ================")
    if not matching:
        print("  -> Not in RSI JSON dataset.")
        continue
        
    for s in matching:
        sig_date = s['signal_date'][:10]
        rsi_l = s.get('rsi')
        rsi_h = s.get('rsi_HTF')
        adx = s.get('adx')
        rng = ((s['signal_high'] - s['signal_low']) / s['signal_low']) * 100 if s.get('signal_low') else 0
        close_replay = s.get('close_lf_replay') or {}
        
        # Check standard filters in UI: LTF 65-90, HTF 65-85, ADX >= 26, Range 3-8%
        pass_rsi_l = 65 <= (rsi_l or 0) <= 90
        pass_rsi_h = 65 <= (rsi_h or 0) <= 85
        pass_adx = (adx or 0) >= 26.0
        pass_range = 3.0 <= rng <= 8.0
        
        pass_ui_filters = pass_rsi_l and pass_rsi_h and pass_adx and pass_range
        
        max_h_lf_pct = s.get('max_high_lookahead_pct')
        close_lf_pct = s.get('close_lookahead_pct')
        
        print(f"  Signal Date: {sig_date} | Entry Date: {(close_replay.get('entry_time') or '')[:10]}")
        rsi_h_str = f"{rsi_h:.1f}" if rsi_h is not None else "None"
        print(f"  RSI_LTF={rsi_l:.1f} (pass={pass_rsi_l}) | RSI_HTF={rsi_h_str} (pass={pass_rsi_h}) | ADX={adx:.1f} (pass={pass_adx}) | Range={rng:.1f}% (pass={pass_range})")
        print(f"  UI Filters Pass: {pass_ui_filters}")
        print(f"  Max High LF %: {max_h_lf_pct} | Close LF %: {close_lf_pct}")
        print(f"  Replay Valid: {close_replay.get('valid')} | ExitReason: {close_replay.get('exit_reason')} | Replay Entry Price: {close_replay.get('entry')}")
        
        # Check 5m simulation for tradesignal project rule
        five_m_file = os.path.join(data_5m_dir, f"{sym}_5m.csv")
        if os.path.exists(five_m_file):
            try:
                df_5m = pd.read_csv(five_m_file)
                df_5m['dt'] = pd.to_datetime(df_5m['datetime'])
                entry_date_str = (close_replay.get('entry_time') or '')[:10]
                day1_5m = df_5m[df_5m['dt'].dt.strftime("%Y-%m-%d") == entry_date_str].reset_index(drop=True)
                
                if not day1_5m.empty:
                    sig_high = s['signal_high']
                    sig_low = s['signal_low']
                    trigger_price = round(sig_high * 1.03, 2)
                    
                    is_triggered = False
                    is_invalidated = False
                    entry_bar_price = None
                    
                    for idx, row in day1_5m.iterrows():
                        bar_time = row['dt'].time()
                        if bar_time <= pd.to_datetime("15:20").time():
                            if row['low'] <= sig_low:
                                is_invalidated = True
                            if row['high'] >= trigger_price:
                                is_triggered = True
                        if bar_time == pd.to_datetime("15:20").time():
                            entry_bar_price = row['close']
                            break
                            
                    print(f"  5m Intraday Check: dip_below_sig_low={is_invalidated}, reached_3pct_high={is_triggered}, entry_320_close={entry_bar_price}")
                    if is_invalidated:
                        print(f"  -> REJECTED BY TRADESIGNAL: Price dipped below signal low ({sig_low}) on Day 1 before 3:20 PM!")
                    elif not is_triggered:
                        print(f"  -> REJECTED BY TRADESIGNAL: Price did not reach +3% high ({trigger_price}) on Day 1 before 3:20 PM!")
                    elif entry_bar_price <= sig_high:
                        print(f"  -> REJECTED BY TRADESIGNAL: 3:20 PM close ({entry_bar_price}) was below signal high ({sig_high})!")
                    else:
                        print(f"  -> PASSED TRADESIGNAL 5M VALIDATION!")
            except Exception as e:
                print(f"  5m Check Error: {e}")
