import json

with open('c:/Users/Yug/Desktop/rsi/tradesignal_comparison_results.json') as f:
    data = json.load(f)

signals = data['signals']

user_trades = [
    ('APEXECO', '2026-06-17', 213.15),
    ('CARBORUNIV', '2026-06-18', 1176.00),
    ('CONSOFINVT', '2026-07-09', 262.45),
    ('FCL', '2026-06-17', 45.00),
    ('GUFICBIO', '2026-06-30', 405.10),
    ('KAMDHENU', '2026-07-24', 35.70),
    ('KERNEX', '2026-07-01', 2295.00),
    ('MODISONLTD', '2026-06-22', 338.25),
    ('OMNI', '2026-07-01', 563.35),
    ('ONELIFECAP', '2026-06-17', 29.48),
    ('PURPLEUTED', '2026-07-02', 481.00),
    ('RANEHOLDIN', '2026-06-17', 1617.00),
    ('SASKEN', '2026-06-18', 2647.90),
    ('SHREEJISPG', '2026-07-13', 570.95),
    ('SSFL', '2026-06-22', 219.85),
    ('VENUSREM', '2026-06-25', 1947.10)
]

print("=== CHECKING THE 16 TRADES IN JSON ===")
found_count = 0
for company, entry_date, entry_price in user_trades:
    matching = [s for s in signals if s['company'] == company]
    if not matching:
        print(f"\n[NOT FOUND] {company}: No signals found in JSON for this company at all!")
        continue
    
    # Check if entry_date or signal_date matches
    found = False
    for s in matching:
        sig_date = s['signal_date'][:10]
        close_replay = s.get('close_lf_replay') or {}
        replay_entry_date = (close_replay.get('entry_time') or '')[:10]
        replay_entry_price = close_replay.get('entry')
        
        # Check matching entry date or signal date
        if entry_date in [sig_date, replay_entry_date] or abs((replay_entry_price or 0) - entry_price) < 1.0:
            found = True
            found_count += 1
            rsi_l = s.get('rsi')
            rsi_h = s.get('rsi_HTF')
            adx = s.get('adx')
            rng = ((s['signal_high'] - s['signal_low']) / s['signal_low']) * 100 if s.get('signal_low') else 0
            
            print(f"\n[MATCHED] {company} (Signal Date: {sig_date}, Entry Date: {replay_entry_date}):")
            print(f"   User Entry: {entry_price} | Replay Entry: {replay_entry_price} (Signal High: {s.get('signal_high')})")
            print(f"   RSI_LTF: {rsi_l:.1f} if rsi_l else None, RSI_HTF: {rsi_h:.1f} if rsi_h else None, ADX: {adx:.1f} if adx else None, Range: {rng:.1f}%")
            print(f"   Replay Outcome: ExitType={close_replay.get('exit_type')}, ExitPrice={close_replay.get('exit_price')}, Target={close_replay.get('Target')}, Stoploss={close_replay.get('Stoploss')}")
            break
            
    if not found:
        print(f"\n[MISMATCH] {company}: Signals exist for this company, but date/entry {entry_date} @ {entry_price} didn't match:")
        for s in matching:
            print(f"   -> Found signal on signal_date={s['signal_date'][:10]}, signal_high={s.get('signal_high')}, close_lf_entry={s.get('close_lf_replay', {}).get('entry')}")

print(f"\nTotal matched: {found_count} / {len(user_trades)}")
