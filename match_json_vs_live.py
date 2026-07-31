import json
import pandas as pd

json_path = r"c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-13-38-48.json"
csv_path = r"C:\Users\Yug\Desktop\tradesignal\rsi_backtest_results_1506_to_2807.csv"

with open(json_path) as f:
    json_data = json.load(f)

json_signals = json_data.get('signals', [])

df_json_list = []
for s in json_signals:
    sym = s.get('company')
    sig_date = str(s.get('signal_date'))[:10]
    entry_date = str(s.get('entry_time'))[:10]
    json_entry = s.get('new_entry') or s.get('entry')
    json_target = s.get('new_target') or s.get('Target')
    json_stoploss = s.get('new_stoploss') or s.get('Stoploss')
    json_exit_reason = s.get('exit_type')
    json_exit_price = s.get('exit_price')
    
    df_json_list.append({
        'Symbol': sym,
        'Signal Date': sig_date,
        'Entry Date': entry_date,
        'JSON Entry': json_entry,
        'JSON Target': json_target,
        'JSON Stoploss': json_stoploss,
        'JSON Exit Reason': json_exit_reason,
        'JSON Exit Price': json_exit_price
    })

df_json = pd.DataFrame(df_json_list)
df_live = pd.read_csv(csv_path)

merged = pd.merge(df_json, df_live, on=['Symbol', 'Signal Date'], how='outer', suffixes=('_JSON', '_LIVE'))

print("=== COMPLETE SIDE-BY-SIDE MATCHING ANALYSIS ===")
print(f"Total Trades in JSON File: {len(df_json)}")
print(f"Total Trades in Live Run: {len(df_live)}")

matches_count = 0
diffs_count = 0

for idx, row in merged.iterrows():
    sym = row['Symbol']
    sig_date = row['Signal Date']
    json_e = row.get('JSON Entry')
    live_e = row.get('Entry Price')
    json_r = row.get('JSON Exit Reason')
    live_r = row.get('Exit Reason')
    
    in_json = pd.notna(json_e)
    in_live = pd.notna(live_e)
    
    print(f"\n------------------------------------------------------------")
    print(f"Symbol: {sym} | Signal Date: {sig_date}")
    
    if in_json and in_live:
        entry_diff = abs(json_e - live_e) if json_e and live_e else 0
        if entry_diff < 0.01 and json_r == live_r:
            print(f"  Status: EXACT 100% MATCH")
            print(f"  Entry: {live_e} | Exit Reason: {live_r}")
            matches_count += 1
        else:
            print(f"  Status: MINOR DIFFERENCE")
            print(f"  JSON Entry: {json_e} vs Live Entry: {live_e} (Diff: {entry_diff:.2f})")
            print(f"  JSON Exit: {json_r} vs Live Exit: {live_r}")
            diffs_count += 1
    elif in_json and not in_live:
        print(f"  Status: Present in JSON, Missing in Live Run")
        diffs_count += 1
    elif not in_json and in_live:
        print(f"  Status: Present in Live Run, Missing in JSON")
        diffs_count += 1

print(f"\n================ SUMMARY ================")
print(f"Exact Matches: {matches_count}")
print(f"Differences / Variations: {diffs_count}")
