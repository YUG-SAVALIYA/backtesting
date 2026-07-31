"""
Compare Backtesting vs Live Scan using EXACT parameters from the UI images:

IMAGE 1 (Backtester form):
  - Start: 2026-06-15, End: 2026-07-28
  - LTF: Day, HTF: Week
  - Supertrend LTF: 21/1.5, HTF: 14/1.0
  - RSI LTF: 14, 65-90  |  HTF: 14, 60-85
  - Target: Fixed 17%,  MaxSL: 5%
  - Min ADX: 0,  Candle Range: 0-100  (backtester form — not live filters)
  - Trade Management: 50% at 10%, SL to breakeven (0%)
  - Look Forward: 1575, Entry LF Bars: 1
  - Pre-Final: H>3%, C>0%

IMAGE 2 (Live Filters toolbar):
  - Gap-Up Mode: gap_up_sl_target_update
  - LTF RSI: 65-90, HTF RSI: 60-85
  - ADX > 26, Range 3-8%
  - (These are POST-PROCESSING filters applied to live scan results in the UI)
"""

import requests
import json

BACKTEST_URL = "http://127.0.0.1:8000/api/backtest"
SCAN_URL = "http://127.0.0.1:8000/api/live-trading/scan"

# ─── BACKTESTER PAYLOAD (exact from last_request.json + image) ────────────────
backtest_payload = {
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
    "min_adx": 0.0,           # form shows 0
    "min_candle_range": 0.0,   # form shows 0
    "max_candle_range": 100.0, # form shows 100
    "trade_management_enabled": True,
    "trade_management_book_pct": 50.0,
    "trade_management_trigger_pct": 10.0,
    "trade_management_targets": [
        {"book_pct": 50.0, "trigger_pct": 10.0, "stoploss_pct": 0.0}
    ]
}

# ─── LIVE SCAN PAYLOAD (same core settings) ────────────────────────────────────
scan_payload = {
    "companies": "ALL",
    "rsi_period": 14,
    "rsi_min": 0,      # live scan returns all, UI filters by ADX/RSI post-scan
    "rsi_max": 100,
    "htf_rsi_period": 14,
    "htf_rsi_min": 0,
    "htf_rsi_max": 100,
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 14,
    "htf_supertrend_multiplier": 1.0,
    "target_level": 17,
    "target_mode": "fixed",
    "max_stoploss_pct": 5.0,
    "entry_offset_pct": 0.0,
    "min_adx": 0,
    "min_candle_range": 0,
    "max_candle_range": 100,
}

print("=" * 70)
print("STEP 1: Running Backtester...")
print("=" * 70)

res = requests.post(BACKTEST_URL, json=backtest_payload, stream=True)
raw_signals = []
for line in res.iter_lines():
    if line:
        s = line.decode("utf-8")
        if s.startswith("data: "):
            try:
                data = json.loads(s[6:])
                if data.get("type") == "complete":
                    raw_signals = data.get("signals", [])
            except Exception:
                pass

# ─── Simulate UI Pre-Final filter ─────────────────────────────────────────────
def compute_pct(val, base_ref):
    if val is None or base_ref is None or base_ref <= 0:
        return None
    return ((float(val) - float(base_ref)) / float(base_ref)) * 100

bt_confirmed = []
bt_rejected = []

for s in raw_signals:
    if s.get("entry_rejected"):
        bt_rejected.append({**s, "reject": "entry_rejected flag"})
        continue
    base_ref = s.get("original_entry") or s.get("signal_high") or s.get("entry")
    if base_ref is None:
        bt_rejected.append({**s, "reject": "no base_ref"})
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
        reasons.append(f"MaxHighLF={max_high_lf_pct} < 3%")
    if close_lf_pct is None or close_lf_pct < 0.0:
        reasons.append(f"CloseLF={close_lf_pct} < 0%")

    if reasons:
        bt_rejected.append({**s, "reject": "; ".join(reasons)})
    else:
        bt_confirmed.append(s)

print(f"\nBacktester: {len(raw_signals)} raw -> {len(bt_confirmed)} confirmed | {len(bt_rejected)} rejected")

# Now apply live filter (ADX>26, Range 3-8%) to backtester results - same as toolbar
bt_live_filtered = [s for s in bt_confirmed
    if (s.get("adx") is None or s.get("adx") >= 26.0) and
       3.0 <= (s.get("candle_range_pct") or 0) <= 8.0 and
       65.0 <= (s.get("rsi") or 0) <= 90.0 and
       60.0 <= (s.get("rsi_htf") or 0) <= 85.0]

print(f"Backtester + Live Filters (ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85): {len(bt_live_filtered)} trades")

print("\n" + "=" * 70)
print("STEP 2: Running Live Scan...")
print("=" * 70)

res2 = requests.post(SCAN_URL, json=scan_payload)
scan_results = res2.json() if res2.ok else []

print(f"\nLive Scan: {len(scan_results)} signals returned")

# Apply same live filters (ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85, both uptrend)
live_filtered = [s for s in scan_results
    if s.get("in_uptrend_ltf") is True and
       s.get("in_uptrend_htf") is True and
       (s.get("adx") or 0) >= 26.0 and
       3.0 <= (s.get("candle_range_pct") or 0) <= 8.0 and
       65.0 <= (s.get("rsi") or 0) <= 90.0 and
       60.0 <= (s.get("rsi_HTF") or s.get("rsi_htf") or 0) <= 85.0]

print(f"Live Scan + Filters (ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85, Uptrend): {len(live_filtered)} signals")

print("\n" + "=" * 70)
print("COMPARISON — BACKTEST CONFIRMED TRADES (Pre-Final H>3%, C>0%)")
print("=" * 70)
bt_syms = {s.get("company") for s in bt_confirmed}
print(f"Count: {len(bt_confirmed)}")
for s in sorted(bt_confirmed, key=lambda x: x.get("company", "")):
    sig = str(s.get("signal_time", s.get("signal_date", "?")))[:10]
    adx = s.get("adx", "?")
    rng = s.get("candle_range_pct", "?")
    rsi = s.get("rsi", "?")
    hrsi = s.get("rsi_htf", "?")
    print(f"  {s.get('company','?'):15s} | Date:{sig} | ADX:{adx} | Range:{rng}% | RSI:{rsi} | HRSI:{hrsi}")

print("\n" + "=" * 70)
print("COMPARISON — LIVE SCAN FILTERED SIGNALS (today's uptrend + filters)")
print("=" * 70)
live_syms = {s.get("company") for s in live_filtered}
print(f"Count: {len(live_filtered)}")
for s in sorted(live_filtered, key=lambda x: x.get("company", "")):
    dt = str(s.get("signal_date", "?"))[:10]
    print(f"  {s.get('company','?'):15s} | Date:{dt} | ADX:{s.get('adx','?')} | Range:{s.get('candle_range_pct','?')}% | RSI:{s.get('rsi','?')} | HRSI:{s.get('rsi_HTF', s.get('rsi_htf','?'))}")

print("\n" + "=" * 70)
print("DIFFERENCE ANALYSIS")
print("=" * 70)
only_in_bt = bt_syms - live_syms
only_in_live = live_syms - bt_syms
in_both = bt_syms & live_syms
print(f"  In BOTH:           {sorted(in_both)}")
print(f"  Only in BACKTEST:  {sorted(only_in_bt)}")
print(f"  Only in LIVE SCAN: {sorted(only_in_live)}")

print("\n" + "=" * 70)
print("PARAMETER DIFFERENCES (Backtest vs Live Scan)")
print("=" * 70)
diffs = [
    ("HTF Supertrend Multiplier", "14/1.0 (from image)", "21/1.5 (ScanRequest default)", "HTF ST period/mult differ"),
    ("RSI filter at scan time", "rsi_min=65,max=90 in StrategySettings", "rsi_min=0,max=100 (scan returns all)", "Live scan returns all — UI filters post"),
    ("ADX filter at scan time", "min_adx=0 (form)", "min_adx=0 (hardcoded)", "Both 0 at scan time, UI toolbar filters ADX>26"),
    ("Candle Range at scan time","0-100 (form)", "0-100 (hardcoded)", "Same — UI toolbar filters 3-8%"),
    ("Pre-Final H>3%, C>0%", "Applied in generate_signals", "NOT APPLIED in live scan", "*** KEY DIFFERENCE ***"),
    ("Signal window", "2026-06-15 to 2026-07-28 (historical)", "Latest candle only (today)", "Different time scope"),
    ("Day-1 confirmation (LF)", "Looks 1 day ahead for High/Close", "No look-ahead (today's candle IS signal)", "Backtest has lookahead, live has none yet"),
]
for d in diffs:
    print(f"\n  Parameter: {d[0]}")
    print(f"    Backtest: {d[1]}")
    print(f"    Live:     {d[2]}")
    print(f"    Note:     {d[3]}")
