"""
Run Live Scanner logic for EVERY DAY between 2026-06-15 and 2026-07-28
and compare day-by-day signals with the Backtesting signals.
"""
import sys
sys.path.insert(0, r'c:\Users\Yug\Desktop\rsi\src')

import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

START_DATE = "2026-06-15"
END_DATE = "2026-07-28"

# Setup strategy with user's parameters
settings = StrategySettings(
    rsi_period=14,
    rsi_min=65.0,
    rsi_max=90.0,
    htf_rsi_period=14,
    htf_rsi_min=60.0,
    htf_rsi_max=85.0,
    supertrend_period=21,
    supertrend_multiplier=1.5,
    htf_supertrend_period=14,
    htf_supertrend_multiplier=1.0,
    min_adx=26.0,
    min_candle_range=3.0,
    max_candle_range=8.0,
    target_mode="fixed",
    max_stoploss_pct=0.05,
    entry_offset_pct=0.0,
)
strategy = RSISupertrendStrategy(settings)

print("Loading daily candles dataset...")
df_all = pd.read_csv(r'c:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv')
df_all['datetime'] = pd.to_datetime(df_all['date'])
df_all = df_all.sort_values(['symbol', 'datetime'])

def make_weekly(df_day):
    df_day = df_day.set_index('datetime')
    weekly = df_day.resample('W').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna(subset=['open'])
    return weekly.reset_index()

symbols = df_all['symbol'].unique()
print(f"Scanning {len(symbols)} companies for signals generated between {START_DATE} and {END_DATE}...")

live_signals_in_range = []

for sym in symbols:
    df_day = df_all[df_all['symbol'] == sym].copy()
    if len(df_day) < 30:
        continue
    df_week = make_weekly(df_day)
    if df_week.empty:
        continue

    try:
        sig_df, _ = strategy.prepare_frames(df_day, df_day, df_week)
        if sig_df.empty or len(sig_df) < 2:
            continue

        # Filter rows within range where signal occurred
        sig_df['sig_date_str'] = sig_df['datetime'].dt.strftime('%Y-%m-%d')
        mask = (sig_df['sig_date_str'] >= START_DATE) & (sig_df['sig_date_str'] <= END_DATE)
        
        # Check rows where signal was generated
        for idx in sig_df[mask].index:
            row = sig_df.loc[idx]
            prev_row = sig_df.loc[idx - 1] if idx - 1 in sig_df.index else None

            in_uptrend_ltf = bool(row.get("in_uptrend", False))
            in_uptrend_htf = bool(row.get("in_uptrend_htf", False)) if "in_uptrend_htf" in row and pd.notna(row["in_uptrend_htf"]) else False

            if not in_uptrend_ltf or not in_uptrend_htf:
                continue

            prev_uptrend = bool(prev_row.get("in_uptrend", False)) if prev_row is not None else False
            just_turned_up = (not prev_uptrend) and in_uptrend_ltf

            if not just_turned_up:
                continue  # Live scanner triggers on signal generation (turn up)

            rsi = float(row.get("rsi", 0) or 0)
            rsi_htf = float(row.get("rsi_htf", 0) or 0)
            adx = float(row.get("adx", 0) or 0)

            o = float(row.get("open", 0) or 0)
            h = float(row.get("high", 0) or 0)
            lo = float(row.get("low", 0) or 0)
            c = float(row.get("close", 0) or 0)
            crange = ((h - lo) / o * 100) if o > 0 else 0

            # Filter checks
            if adx < 26.0: continue
            if not (3.0 <= crange <= 8.0): continue
            if not (65.0 <= rsi <= 90.0): continue
            if not (60.0 <= rsi_htf <= 85.0): continue

            live_signals_in_range.append({
                "company": sym,
                "signal_date": row['sig_date_str'],
                "adx": round(adx, 2),
                "rsi": round(rsi, 2),
                "rsi_htf": round(rsi_htf, 2),
                "candle_range_pct": round(crange, 2),
                "signal_high": h,
                "signal_close": c
            })

    except Exception as e:
        pass

print(f"\nLive Scanner signals generated between {START_DATE} and {END_DATE}: {len(live_signals_in_range)}")

# ── Load Backtest Results ──
with open(r'c:\Users\Yug\Desktop\rsi\output\backtest_2026-07-29_21-35-31_3008stocks.json') as f:
    bt_data = json.load(f)

bt_raw = bt_data.get('signals', [])

def compute_pct(val, base_ref):
    if val is None or base_ref is None or float(base_ref) <= 0:
        return None
    return ((float(val) - float(base_ref)) / float(base_ref)) * 100

bt_confirmed_17 = []
for s in bt_raw:
    if s.get("entry_rejected"): continue
    sig_date = str(s.get("signal_date", s.get("entry_time","?")))[:10]
    if not (START_DATE <= sig_date <= END_DATE): continue

    base_ref = float(s.get("original_entry") or s.get("signal_high") or s.get("entry") or 0)
    if base_ref <= 0: continue

    cl_pct = float(s["close_lookahead_pct"]) if s.get("close_lookahead_pct") is not None else compute_pct(s.get("close_lookahead"), base_ref)
    mh_pct = float(s["max_high_lookahead_pct"]) if s.get("max_high_lookahead_pct") is not None else compute_pct(s.get("max_high_lookahead"), base_ref)

    if mh_pct is None or mh_pct < 3.0: continue
    if cl_pct is None or cl_pct < 0.0: continue
    if s.get("sl_hit_lookahead") is True: continue

    adx = s.get("adx") or 0
    so = float(s.get("signal_open") or 0)
    sh = float(s.get("signal_high") or 0)
    sl = float(s.get("signal_low") or 0)
    crange = ((sh - sl) / so * 100) if so > 0 else 0
    rsi  = s.get("rsi") or 0
    hrsi = s.get("rsi_HTF") or s.get("rsi_htf") or 0

    if adx < 26.0: continue
    if not (3.0 <= crange <= 8.0): continue
    if not (65.0 <= rsi <= 90.0): continue
    if not (60.0 <= hrsi <= 85.0): continue

    bt_confirmed_17.append({
        "company": s.get("company"),
        "signal_date": sig_date,
        "adx": round(adx, 2),
        "rsi": round(rsi, 2),
        "candle_range_pct": round(crange, 2),
        "max_high_lf_pct": round(mh_pct, 2),
        "close_lf_pct": round(cl_pct, 2)
    })

print(f"Backtest Confirmed Trades between {START_DATE} and {END_DATE}: {len(bt_confirmed_17)}")

print("\n" + "=" * 75)
print(f"LIVE SCAN SIGNALS DETECTED IN RANGE ({START_DATE} to {END_DATE})")
print("=" * 75)
live_signals_in_range.sort(key=lambda x: (x['signal_date'], x['company']))
for item in live_signals_in_range:
    print(f"  {item['company']:15s} | Date: {item['signal_date']} | ADX: {item['adx']:5.1f} | Range: {item['candle_range_pct']:4.1f}% | RSI: {item['rsi']:4.1f} | HRSI: {item['rsi_htf']:4.1f}")

live_map = {(x['company'], x['signal_date']): x for x in live_signals_in_range}
bt_map   = {(x['company'], x['signal_date']): x for x in bt_confirmed_17}

live_keys = set(live_map.keys())
bt_keys   = set(bt_map.keys())

print("\n" + "=" * 75)
print("SIDE-BY-SIDE MATCHING ANALYSIS")
print("=" * 75)
print(f"  Exact Matches (Same Symbol & Date): {len(live_keys & bt_keys)} / {len(bt_keys)}")
print(f"  Signals in Live Scan:               {len(live_keys)}")
print(f"  Confirmed Trades in Backtest:       {len(bt_keys)}")

only_in_live = live_keys - bt_keys
only_in_bt   = bt_keys - live_keys

if only_in_bt:
    print(f"\n  In Backtest but not in Live Signal Turn-Up:")
    for k in sorted(only_in_bt):
        print(f"    - {k[0]:15s} on {k[1]}")

if only_in_live:
    print(f"\n  In Live Signal Turn-Up but rejected in Backtest by Pre-Final:")
    for k in sorted(only_in_live):
        print(f"    - {k[0]:15s} on {k[1]}")