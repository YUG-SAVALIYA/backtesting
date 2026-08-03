import json
import os

filepath = 'output/backtest_results_2026-06-19-04-39-42.json'
tmp_filepath = filepath + '.tmp'

print("Loading JSON file...")
with open(filepath, 'r') as f:
    data = json.load(f)

print("Original counts:")
signals = data.get('signals', [])
base_signals = data.get('baseSignals', [])
print(f"  signals: {len(signals)}")
print(f"  baseSignals: {len(base_signals)}")

# Filter signals
filtered_signals = [s for s in signals if s.get('company') not in ('SHRIPISTON', 'VISHNU')]
removed_signals = len(signals) - len(filtered_signals)
data['signals'] = filtered_signals

# Filter baseSignals
filtered_base = [s for s in base_signals if s.get('company') not in ('SHRIPISTON', 'VISHNU')]
removed_base = len(base_signals) - len(filtered_base)
data['baseSignals'] = filtered_base

print(f"Removed from signals: {removed_signals} (new count: {len(filtered_signals)})")
print(f"Removed from baseSignals: {removed_base} (new count: {len(filtered_base)})")

# Filter entryLookaheadVariants
removed_el = {}
el_v = data.get('entryLookaheadVariants', {})
for k, v in el_v.items():
    if isinstance(v, list):
        filtered_v = [s for s in v if s.get('company') not in ('SHRIPISTON', 'VISHNU')]
        removed_el[k] = len(v) - len(filtered_v)
        el_v[k] = filtered_v
print(f"Removed from entryLookaheadVariants: {removed_el}")

# Filter baseEntryLookaheadVariants
removed_bel = {}
base_el_v = data.get('baseEntryLookaheadVariants', {})
for k, v in base_el_v.items():
    if isinstance(v, list):
        filtered_v = [s for s in v if s.get('company') not in ('SHRIPISTON', 'VISHNU')]
        removed_bel[k] = len(v) - len(filtered_v)
        base_el_v[k] = filtered_v
print(f"Removed from baseEntryLookaheadVariants: {removed_bel}")

# Filter companies list in settings
companies_str = data.get('settings', {}).get('companies', '')
if isinstance(companies_str, str) and companies_str:
    companies_list = companies_str.split(',')
    filtered_companies = [c for c in companies_list if c not in ('SHRIPISTON', 'VISHNU')]
    removed_companies = len(companies_list) - len(filtered_companies)
    data['settings']['companies'] = ','.join(filtered_companies)
    print(f"Removed from settings['companies']: {removed_companies} (new count: {len(filtered_companies)})")
    # Verify they are really not in it
    print(f"  SHRIPISTON still in settings['companies']? {'SHRIPISTON' in data['settings']['companies']}")
    print(f"  VISHNU still in settings['companies']? {'VISHNU' in data['settings']['companies']}")

print("Saving filtered JSON to temporary file...")
with open(tmp_filepath, 'w') as f:
    json.dump(data, f)

print("Renaming temporary file to overwrite original...")
if os.path.exists(filepath):
    os.remove(filepath)
os.rename(tmp_filepath, filepath)

print("Verifying the updated file...")
with open(filepath, 'r') as f:
    data_check = json.load(f)

signals_check = data_check.get('signals', [])
base_signals_check = data_check.get('baseSignals', [])
shripiston_signals = [s for s in signals_check if s.get('company') == 'SHRIPISTON']
vishnu_signals = [s for s in signals_check if s.get('company') == 'VISHNU']

print(f"Verification: total signals count = {len(signals_check)}")
print(f"Verification: SHRIPISTON signals = {len(shripiston_signals)}")
print(f"Verification: VISHNU signals = {len(vishnu_signals)}")
print("Filtering finished successfully!")
