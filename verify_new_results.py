import json

with open('c:/Users/Yug/Desktop/rsi/tradesignal_comparison_results.json') as f:
    data = json.load(f)

signals = data['signals']
print(f"Total signals in file: {len(signals)}")

live_companies = ['CONSOFINVT', 'MODISONLTD', 'ONELIFECAP', 'AEGISLOG', 'RADICO', 'HESTERBIO', 'EQUITASBNK', 'CENTUM', 'FCL']
print('\nLive system companies check:')
for s in signals:
    if s['company'] in live_companies:
        rsi_h = s.get('rsi_HTF')
        rsi_h_str = f"{rsi_h:.1f}" if rsi_h is not None else "None"
        print(f"  {s['company']} ({s['signal_date'][:10]}): RSI_LTF={s.get('rsi'):.1f}, RSI_HTF={rsi_h_str}, ADX={s.get('adx'):.1f}")

print('\nSample 10 signals:')
for s in signals[:10]:
    rsi_h = s.get('rsi_HTF')
    rsi_h_str = f"{rsi_h:.1f}" if rsi_h is not None else "None"
    print(f"  {s['company']} ({s['signal_date'][:10]}): RSI_LTF={s.get('rsi'):.1f}, RSI_HTF={rsi_h_str}, ADX={s.get('adx'):.1f}")
