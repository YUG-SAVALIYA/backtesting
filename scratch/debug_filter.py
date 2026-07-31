import json, glob, os

files = glob.glob('D:/AT/AI_Trading/output/backtest_*.json')
latest = max(files, key=os.path.getmtime)
print(f'File: {os.path.basename(latest)}')

with open(latest, 'r') as f:
    data = json.load(f)

signals = data.get('signals', [])
elv = data.get('entry_lookahead_variants', {})
selected_bars = data.get('selected_entry_lookahead_bars', 2)
variants = elv if elv else {str(selected_bars): signals}
active_signals = list(variants.values())[0] if variants else signals
print(f'Total active signals: {len(active_signals)}')

meets_3_pct = []
meets_both = []

for s in active_signals:
    max_high_pct = s.get('max_high_lookahead_pct') or 0
    close_pct = s.get('close_lookahead_pct') or 0
    if max_high_pct >= 3.0:
        meets_3_pct.append(s)
        if close_pct > 0:
            meets_both.append(s)

print(f'Signals that hit 3% high during lookahead: {len(meets_3_pct)}')
print(f'Signals that hit 3% high AND closed positive during lookahead: {len(meets_both)}')
