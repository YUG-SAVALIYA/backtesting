"""
Compare Backtest (Jun 15 - Jul 28) with Live Scan using SAME parameters and filters:
- ADX > 26, Range 3-8%, RSI LTF 65-90, RSI HTF 60-85
- Both Uptrend (LTF & HTF)
- Pre-Final: H > 3%, C > 0%
"""
import json, requests

SCAN_URL = "http://127.0.0.1:8000/api/live-trading/scan"
END_DATE = "2026-07-28"

# ─── Load saved backtest (40 trades = pre-final confirmed + ADX>26 + Range 3-8%) ─
with open(r'c:\Users\Yug\Desktop\rsi\output\backtest_2026-07-29_21-35-31_3008stocks.json') as f:
    bt_data = json.load(f)

bt_raw = bt_data.get('signals', [])

# Apply same pre-final + toolbar filters (mirrors UI behavior exactly)
def compute_pct(val, base_ref):
    if val is None or base_ref is None or float(base_ref) <= 0:
        return None
    return ((float(val) - float(base_ref)) / float(base_ref)) * 100

bt_confirmed = []
bt_pre_final_rejected = []
bt_adx_range_rejected = []

for s in bt_raw:
    if s.get("entry_rejected"):
        continue
    sig_date = str(s.get("signal_date", s.get("entry_time","?")))[:10]
    if sig_date > END_DATE:
        continue

    base_ref = s.get("original_entry") or s.get("signal_high") or s.get("entry")
    if not base_ref:
        continue
    base_ref = float(base_ref)

    close_lf_pct = float(s["close_lookahead_pct"]) if s.get("close_lookahead_pct") is not None else compute_pct(s.get("close_lookahead"), base_ref)
    max_h_lf_pct = float(s["max_high_lookahead_pct"]) if s.get("max_high_lookahead_pct") is not None else compute_pct(s.get("max_high_lookahead"), base_ref)

    reasons = []
    if s.get("sl_hit_lookahead") is True:
        reasons.append("SL hit LF")
    if max_h_lf_pct is None or max_h_lf_pct < 3.0:
        reasons.append(f"MaxHighLF={round(max_h_lf_pct,2) if max_h_lf_pct else None} < 3%")
    if close_lf_pct is None or close_lf_pct < 0.0:
        reasons.append(f"CloseLF={round(close_lf_pct,2) if close_lf_pct else None} < 0%")

    if reasons:
        bt_pre_final_rejected.append(s)
        continue

    # Toolbar filters
    adx = s.get("adx") or 0
    sopen = float(s.get("signal_open") or 0)
    shigh = float(s.get("signal_high") or 0)
    slow  = float(s.get("signal_low") or 0)
    crange = ((shigh - slow) / sopen * 100) if sopen > 0 else 0
    rsi  = s.get("rsi") or 0
    hrsi = s.get("rsi_HTF") or s.get("rsi_htf") or 0

    if adx < 26:
        bt_adx_range_rejected.append({**s, "reject_reason": f"ADX={adx:.1f} < 26"})
        continue
    if not (3.0 <= crange <= 8.0):
        bt_adx_range_rejected.append({**s, "reject_reason": f"Range={crange:.1f}% not in 3-8%"})
        continue
    if not (65.0 <= rsi <= 90.0):
        bt_adx_range_rejected.append({**s, "reject_reason": f"RSI={rsi:.1f} not in 65-90"})
        continue
    if not (60.0 <= hrsi <= 85.0):
        bt_adx_range_rejected.append({**s, "reject_reason": f"HRSI={hrsi:.1f} not in 60-85"})
        continue

    bt_confirmed.append(s)

print("=" * 65)
print("BACKTEST (Jun 15 - Jul 28) — After ALL Filters")
print("=" * 65)
print(f"  Raw signals from backend:            {len(bt_raw)}")
print(f"  Rejected by Pre-Final (H>3%,C>0%):  {len(bt_pre_final_rejected)}")
print(f"  Rejected by Toolbar (ADX,Range,RSI): {len(bt_adx_range_rejected)}")
print(f"  CONFIRMED TRADES:                    {len(bt_confirmed)}")
print()
bt_syms = {}
for s in bt_confirmed:
    sym = s.get("company","?")
    sig = str(s.get("signal_date", s.get("entry_time","?")))[:10]
    adx = s.get("adx",0)
    sopen = float(s.get("signal_open") or 0)
    shigh = float(s.get("signal_high") or 0)
    slow  = float(s.get("signal_low") or 0)
    crange = ((shigh - slow) / sopen * 100) if sopen > 0 else 0
    rsi   = s.get("rsi",0)
    hrsi  = s.get("rsi_HTF") or s.get("rsi_htf",0)
    cl_pct = float(s.get("close_lookahead_pct",0) or 0)
    mh_pct = float(s.get("max_high_lookahead_pct",0) or 0)
    bt_syms[sym] = sig
    print(f"  {sym:15s} | {sig} | ADX:{adx:.1f} | Rng:{crange:.1f}% | RSI:{rsi:.0f} | H:{mh_pct:.1f}% | C:{cl_pct:.2f}%")

# ─── LIVE SCAN ──────────────────────────────────────────────────
print()
print("=" * 65)
print("LIVE SCAN — Running now...")
print("=" * 65)

scan_payload = {
    "companies": "ALL",
    "rsi_period": 14,
    "rsi_min": 0, "rsi_max": 100,
    "htf_rsi_period": 14,
    "htf_rsi_min": 0, "htf_rsi_max": 100,
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 14,
    "htf_supertrend_multiplier": 1.0,
    "target_level": 17,
    "target_mode": "fixed",
    "max_stoploss_pct": 5.0,
    "entry_offset_pct": 0.0,
    "min_adx": 0, "min_candle_range": 0, "max_candle_range": 100,
}

res2 = requests.post(SCAN_URL, json=scan_payload)
scan_all = res2.json() if res2.ok else []

live_confirmed = []
for s in scan_all:
    sig_date = str(s.get("signal_date",""))[:10]
    if sig_date > END_DATE:
        continue
    if s.get("in_uptrend_ltf") is not True:
        continue
    if s.get("in_uptrend_htf") is not True:
        continue
    adx   = s.get("adx") or 0
    rsi   = s.get("rsi") or 0
    hrsi  = s.get("rsi_HTF") or s.get("rsi_htf") or 0
    sopen = float(s.get("signal_open") or 0)
    shigh = float(s.get("signal_high") or 0)
    slow  = float(s.get("signal_low") or 0)
    crange = ((shigh - slow) / sopen * 100) if sopen > 0 else 0

    if adx < 26: continue
    if not (3.0 <= crange <= 8.0): continue
    if not (65.0 <= rsi <= 90.0): continue
    if not (60.0 <= hrsi <= 85.0): continue

    live_confirmed.append(s)

live_syms = {s.get("company"): str(s.get("signal_date",""))[:10] for s in live_confirmed}

print(f"  Total live scan signals:      {len(scan_all)}")
print(f"  After all filters (till {END_DATE}): {len(live_confirmed)}")
print()
for s in sorted(live_confirmed, key=lambda x: x.get("company","")):
    sym = s.get("company","?")
    dt  = str(s.get("signal_date","?"))[:10]
    adx = s.get("adx",0)
    rsi = s.get("rsi",0)
    hrsi= s.get("rsi_HTF") or s.get("rsi_htf",0)
    sopen = float(s.get("signal_open") or 0)
    shigh = float(s.get("signal_high") or 0)
    slow  = float(s.get("signal_low") or 0)
    crange = ((shigh - slow) / sopen * 100) if sopen > 0 else 0
    print(f"  {sym:15s} | {dt} | ADX:{adx:.1f} | Rng:{crange:.1f}% | RSI:{rsi:.0f}")

# ─── DIFF ───────────────────────────────────────────────────────
print()
print("=" * 65)
print("DIFFERENCE (Backtest vs Live)")
print("=" * 65)
bt_set  = set(bt_syms.keys())
live_set = set(live_syms.keys())
both = bt_set & live_set
only_bt   = bt_set - live_set
only_live = live_set - bt_set

print(f"  In BOTH:           {len(both):2d} -> {sorted(both)}")
print(f"  Only in BACKTEST:  {len(only_bt):2d} -> {sorted(only_bt)}")
print(f"  Only in LIVE:      {len(only_live):2d} -> {sorted(only_live)}")
