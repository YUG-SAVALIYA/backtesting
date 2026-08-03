import json, requests

# --- Load saved file (40 trades) ---
with open(r'c:\Users\Yug\Desktop\rsi\output\filtered_backtest_results_2026-07-29-15-45-59.json') as f:
    data = json.load(f)

saved_signals = data.get('signals', [])
saved_syms = {s.get('company') for s in saved_signals}
saved_by_sym = {s.get('company'): s for s in saved_signals}

# --- Run fresh backtest with same settings (42 trades from compare script) ---
payload = {
    "companies": "ALL",
    "start_date": "2026-06-15",
    "end_date": "2026-07-28",
    "ltf": "Day",
    "htf": "Week",
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 14,
    "htf_supertrend_multiplier": 1.0,
    "rsi_ltf_period": 14,
    "rsi_ltf_min": 65.0,
    "rsi_ltf_max": 90.0,
    "rsi_htf_period": 14,
    "rsi_htf_min": 60.0,
    "rsi_htf_max": 85.0,
    "target_level": 17,
    "look_forward_limit": 1575,
    "entry_lookahead_bars": 1,
    "pre_final_max_high_lf_min": 3.0,
    "pre_final_close_lf_min": 0.0,
    "max_stoploss_pct": 5.0,
    "stoploss_mode": "signal_candle_low",
    "max_parallel": 4,
    "target_mode": "fixed",
    "atr_multiplier": 2.0,
    "entry_offset_pct": 0.0,
    "min_adx": 0.0,
    "min_candle_range": 0.0,
    "max_candle_range": 100.0,
    "trade_management_enabled": True,
    "trade_management_book_pct": 50.0,
    "trade_management_trigger_pct": 10.0,
    "trade_management_targets": [{"book_pct": 50.0, "trigger_pct": 10.0, "stoploss_pct": 0.0}]
}

print("Running fresh backtest to get raw signals...")
res = requests.post("http://127.0.0.1:8000/api/backtest", json=payload, stream=True)
raw_signals = []
for line in res.iter_lines():
    if line:
        s = line.decode("utf-8")
        if s.startswith("data: "):
            try:
                d = json.loads(s[6:])
                if d.get("type") == "complete":
                    raw_signals = d.get("signals", [])
            except Exception:
                pass

print(f"API returned {len(raw_signals)} raw signals")

# Apply same pre-final filter as UI does (H>3%, C>0%)
def compute_pct(val, base_ref):
    if val is None or base_ref is None or float(base_ref) <= 0:
        return None
    return ((float(val) - float(base_ref)) / float(base_ref)) * 100

api_confirmed = []
api_rejected = []
for s in raw_signals:
    if s.get("entry_rejected"):
        api_rejected.append({**s, "reject": "entry_rejected"})
        continue
    base_ref = s.get("original_entry") or s.get("signal_high") or s.get("entry")
    if base_ref is None:
        api_rejected.append({**s, "reject": "no base_ref"})
        continue
    base_ref = float(base_ref)
    close_lf_pct = compute_pct(s.get("close_lookahead"), base_ref) if s.get("close_lookahead") else None
    if close_lf_pct is None and s.get("close_lookahead_pct") is not None:
        close_lf_pct = float(s["close_lookahead_pct"])
    max_high_lf_pct = compute_pct(s.get("max_high_lookahead"), base_ref) if s.get("max_high_lookahead") else None
    if max_high_lf_pct is None and s.get("max_high_lookahead_pct") is not None:
        max_high_lf_pct = float(s["max_high_lookahead_pct"])

    reasons = []
    if s.get("sl_hit_lookahead") is True:
        reasons.append("SL hit LF")
    if max_high_lf_pct is None or max_high_lf_pct < 3.0:
        reasons.append(f"MaxHighLF={round(max_high_lf_pct,2) if max_high_lf_pct else None} < 3%")
    if close_lf_pct is None or close_lf_pct < 0.0:
        reasons.append(f"CloseLF={round(close_lf_pct,2) if close_lf_pct else None} < 0%")

    if reasons:
        api_rejected.append({**s, "reject": "; ".join(reasons)})
    else:
        api_confirmed.append(s)

api_syms = {s.get("company") for s in api_confirmed}

print(f"\nAPI (fresh run) after pre-final: {len(api_confirmed)} confirmed")
print(f"Saved file:                      {len(saved_signals)} confirmed")

only_in_api = api_syms - saved_syms
only_in_saved = saved_syms - api_syms
in_both = api_syms & saved_syms

print(f"\nIn BOTH:          {len(in_both)} - {sorted(in_both)}")
print(f"Only in API:      {len(only_in_api)} - {sorted(only_in_api)}")
print(f"Only in SAVED:    {len(only_in_saved)} - {sorted(only_in_saved)}")

# Show entry dates compared for all trades
print("\n=== DATE COMPARISON (saved file vs fresh run) ===")
print(f"{'Symbol':15s} | {'Saved Entry':12s} | {'API SignalDate':13s} | Status")
print("-" * 70)

api_by_sym = {s.get("company"): s for s in api_confirmed}

all_syms = sorted(api_syms | saved_syms)
for sym in all_syms:
    saved_date = str(saved_by_sym[sym].get('entry_time', '?'))[:10] if sym in saved_by_sym else "MISSING"
    api_date = str(api_by_sym[sym].get('signal_time', api_by_sym[sym].get('entry_time', '?')))[:10] if sym in api_by_sym else "MISSING"
    match = "MATCH" if saved_date == api_date else ("ONLY_API" if sym not in saved_syms else ("ONLY_SAVED" if sym not in api_syms else "DATE_DIFF"))
    print(f"{sym:15s} | {saved_date:12s} | {api_date:13s} | {match}")

# Check what happened to HIRECT and MSPL (in API but maybe not in saved)
print("\n=== API REJECTED (not confirmed) ===")
print(f"{'Symbol':15s} | {'Reject Reason'}")
print("-" * 60)
for s in sorted(api_rejected, key=lambda x: x.get('company','')):
    sym = s.get('company','?')
    reason = s.get('reject','?')
    sig_date = str(s.get('signal_time', s.get('signal_date','?')))[:10]
    print(f"{sym:15s} | {sig_date} | {reason}")
