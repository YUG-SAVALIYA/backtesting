"""
Simulate live scan as-of July 28, 2026 using combined daily candles CSV.
Applies same filters: ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85, both uptrend.
Does NOT apply Pre-Final (live scan can't look ahead).
"""
import sys
sys.path.insert(0, r'c:\Users\Yug\Desktop\rsi\src')

import pandas as pd
import warnings
warnings.filterwarnings('ignore')

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

END_DATE = "2026-07-28"

# Strategy settings matching image parameters
settings = StrategySettings(
    rsi_period=14,
    rsi_min=0,    # No RSI filter at scan time - apply post
    rsi_max=100,
    htf_rsi_period=14,
    htf_rsi_min=0,
    htf_rsi_max=100,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    htf_supertrend_period=14,
    htf_supertrend_multiplier=1.0,
    min_adx=0,
    min_candle_range=0,
    max_candle_range=100,
    target_mode="fixed",
    max_stoploss_pct=0.05,
    entry_offset_pct=0.0,
    min_close_lf_pct=None,   # No pre-final in live scan
)
strategy = RSISupertrendStrategy(settings)

print(f"Loading combined CSV...")
df_all = pd.read_csv(r'c:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv')
df_all['datetime'] = pd.to_datetime(df_all['date'])
df_all = df_all[df_all['datetime'] <= pd.Timestamp(END_DATE)]
df_all = df_all.sort_values(['symbol', 'datetime'])

# Build weekly candles by resampling daily
def make_weekly(df_day):
    df_day = df_day.set_index('datetime')
    weekly = df_day.resample('W').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna(subset=['open'])
    weekly = weekly.reset_index()
    return weekly

symbols = df_all['symbol'].unique()
print(f"Processing {len(symbols)} companies as-of {END_DATE}...")

results = []
errors = []

for i, sym in enumerate(symbols):
    try:
        df_day = df_all[df_all['symbol'] == sym].copy()
        if len(df_day) < 30:
            continue

        df_week = make_weekly(df_day)
        if df_week.empty:
            continue

        sig_df, _exec_df = strategy.prepare_frames(df_day, df_day, df_week)
        if sig_df.empty or len(sig_df) < 2:
            continue

        row = sig_df.iloc[-1]
        prev_row = sig_df.iloc[-2]

        in_uptrend_ltf = bool(row.get("in_uptrend", False))
        in_uptrend_htf = bool(row.get("in_uptrend_htf", False)) if "in_uptrend_htf" in row and pd.notna(row["in_uptrend_htf"]) else False

        if not in_uptrend_ltf or not in_uptrend_htf:
            continue

        # Check if it JUST turned uptrend on last candle (signal candle)
        prev_uptrend = bool(prev_row.get("in_uptrend", False))
        just_turned_up = (not prev_uptrend) and in_uptrend_ltf

        rsi = float(row.get("rsi", 0) or 0)
        rsi_htf = float(row.get("rsi_htf", 0) or 0)
        adx = float(row.get("adx", 0) or 0)

        o = float(row.get("open", 0) or 0)
        h = float(row.get("high", 0) or 0)
        lo = float(row.get("low", 0) or 0)
        c = float(row.get("close", 0) or 0)
        crange = ((h - lo) / o * 100) if o > 0 else 0

        sig_date = str(row["datetime"])[:10]

        results.append({
            "company": sym,
            "signal_date": sig_date,
            "just_turned_up": just_turned_up,
            "in_uptrend_ltf": in_uptrend_ltf,
            "in_uptrend_htf": in_uptrend_htf,
            "rsi": round(rsi, 2),
            "rsi_htf": round(rsi_htf, 2),
            "adx": round(adx, 2),
            "candle_range_pct": round(crange, 2),
            "signal_high": h,
            "signal_low": lo,
            "signal_open": o,
            "signal_close": c,
        })
    except Exception as e:
        errors.append((sym, str(e)))

# Apply live filters: both uptrend, ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85
live_signals = [r for r in results if r["in_uptrend_ltf"] and r["in_uptrend_htf"]]
print(f"\nTotal stocks in uptrend (both LTF+HTF): {len(live_signals)}")

filtered = [r for r in live_signals
    if r["adx"] >= 26
    and 3.0 <= r["candle_range_pct"] <= 8.0
    and 65.0 <= r["rsi"] <= 90.0
    and 60.0 <= r["rsi_htf"] <= 85.0]

print(f"After filters (ADX>26, Range 3-8%, RSI 65-90, HRSI 60-85): {len(filtered)}")

# Only signal candle (just turned up) - this is what live scan truly represents
just_turned = [r for r in filtered if r["just_turned_up"]]
print(f"Of those, JUST TURNED UPTREND today ({END_DATE}): {len(just_turned)}")

print("\n" + "=" * 65)
print(f"LIVE SCAN SIGNALS as-of {END_DATE} (All stocks currently in uptrend)")
print("=" * 65)
filtered.sort(key=lambda x: x["company"])
for r in filtered:
    newly = " [NEW SIGNAL]" if r["just_turned_up"] else ""
    print(f"  {r['company']:15s} | {r['signal_date']} | ADX:{r['adx']:.1f} | Rng:{r['candle_range_pct']:.1f}% | RSI:{r['rsi']:.0f} | HRSI:{r['rsi_htf']:.0f}{newly}")

if errors:
    print(f"\nErrors: {len(errors)} stocks could not be processed")

# Now compare with backtest confirmed trades (17 trades)
import json
with open(r'c:\Users\Yug\Desktop\rsi\output\backtest_2026-07-29_21-35-31_3008stocks.json') as f:
    bt_data = json.load(f)
bt_raw = bt_data.get('signals', [])

# Apply pre-final + toolbar filters to backtest
def compute_pct(val, base_ref):
    if val is None or base_ref is None or float(base_ref) <= 0:
        return None
    return ((float(val) - float(base_ref)) / float(base_ref)) * 100

bt_confirmed = set()
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
    cl_pct = float(s["close_lookahead_pct"]) if s.get("close_lookahead_pct") is not None else compute_pct(s.get("close_lookahead"), base_ref)
    mh_pct = float(s["max_high_lookahead_pct"]) if s.get("max_high_lookahead_pct") is not None else compute_pct(s.get("max_high_lookahead"), base_ref)
    if mh_pct is None or mh_pct < 3.0: continue
    if cl_pct is None or cl_pct < 0.0: continue
    adx = s.get("adx") or 0
    so = float(s.get("signal_open") or 0)
    sh = float(s.get("signal_high") or 0)
    sl = float(s.get("signal_low") or 0)
    crange = ((sh - sl) / so * 100) if so > 0 else 0
    rsi  = s.get("rsi") or 0
    hrsi = s.get("rsi_HTF") or s.get("rsi_htf") or 0
    if adx < 26: continue
    if not (3.0 <= crange <= 8.0): continue
    if not (65.0 <= rsi <= 90.0): continue
    if not (60.0 <= hrsi <= 85.0): continue
    bt_confirmed.add(s.get("company"))

live_set = {r["company"] for r in filtered}

print("\n" + "=" * 65)
print("COMPARISON: Backtest (17 confirmed) vs Live Scan (uptrend stocks)")
print("=" * 65)
both = bt_confirmed & live_set
only_bt = bt_confirmed - live_set
only_live = live_set - bt_confirmed
print(f"  In BOTH (backtest confirmed + currently in uptrend): {len(both)} -> {sorted(both)}")
print(f"  Only in BACKTEST (exited uptrend since signal):      {len(only_bt)} -> {sorted(only_bt)}")
print(f"  Only in LIVE (new uptrend, no historical signal):    {len(only_live)} -> {sorted(only_live)}")
