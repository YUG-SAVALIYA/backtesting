import json

filepath = 'output/backtest_results_2026-06-19-04-39-42.json'
with open(filepath, 'r') as f:
    data = json.load(f)

el_keys = list(data.get('entryLookaheadVariants', {}).keys())
base_el_keys = list(data.get('baseEntryLookaheadVariants', {}).keys())
print(f"entryLookaheadVariants keys: {el_keys}")
print(f"baseEntryLookaheadVariants keys: {base_el_keys}")

el_v = data.get('entryLookaheadVariants', {})
if el_v:
    k0 = list(el_v.keys())[0]
    print(f"Keys of entryLookaheadVariants[{k0}][0]:", list(el_v[k0][0].keys()))

base_el_v = data.get('baseEntryLookaheadVariants', {})
if base_el_v:
    k0 = list(base_el_v.keys())[0]
    print(f"Keys of baseEntryLookaheadVariants[{k0}][0]:", list(base_el_v[k0][0].keys()))

# Let's verify if they are aligned by index (i.e. do they have the same company and entry_time at the same index?)
signals = data.get('signals', [])
for k in el_keys:
    lst = el_v[k]
    mismatches = 0
    for i in range(min(len(signals), len(lst))):
        if signals[i].get('company') != lst[i].get('company') or signals[i].get('entry_time') != lst[i].get('entry_time'):
            mismatches += 1
            if mismatches <= 2:
                print(f"Mismatch at index {i} for entryLookaheadVariants[{k}]: signals={signals[i].get('company')}/{signals[i].get('entry_time')}, el={lst[i].get('company')}/{lst[i].get('entry_time')}")
    print(f"Mismatches in entryLookaheadVariants[{k}]: {mismatches}")

base_signals = data.get('baseSignals', [])
for k in base_el_keys:
    lst = base_el_v[k]
    mismatches = 0
    for i in range(min(len(base_signals), len(lst))):
        if base_signals[i].get('company') != lst[i].get('company') or base_signals[i].get('entry_time') != lst[i].get('entry_time'):
            mismatches += 1
    print(f"Mismatches in baseEntryLookaheadVariants[{k}]: {mismatches}")
