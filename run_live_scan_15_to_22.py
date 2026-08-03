"""
Run Live Scan logic from 2026-06-15 to 2026-07-22 using Candle Range formula: ((High - Low) / Open) * 100
Parameters:
  - LTF Supertrend: 21 / 1.5
  - HTF Supertrend: 14 / 1.0
  - RSI LTF: 65-90
  - RSI HTF: 60-85
  - ADX > 26
  - Candle Range: 3.0% to 8.0% (formula: (High - Low) / Open * 100)
  - Both LTF & HTF Uptrend
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
END_DATE = "2026-07-22"

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

print("Loading daily candles data...")
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
print(f"Scanning {len(symbols)} companies for live signals from {START_DATE} to {END_DATE}...")

live_signals = []

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

        sig_df['sig_date_str'] = sig_df['datetime'].dt.strftime('%Y-%m-%d')
        mask = (sig_df['sig_date_str'] >= START_DATE) & (sig_df['sig_date_str'] <= END_DATE)

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
                continue

            rsi = float(row.get("rsi", 0) or 0)
            rsi_htf = float(row.get("rsi_htf", 0) or 0)
            adx = float(row.get("adx", 0) or 0)

            o = float(row.get("open", 0) or 0)
            h = float(row.get("high", 0) or 0)
            lo = float(row.get("low", 0) or 0)

            # Candle Range Formula: ((High - Low) / Open) * 100
            crange = ((h - lo) / o * 100.0) if o > 0 else 0

            # Filter checks
            if adx < 26.0: continue
            if not (3.0 <= crange <= 8.0): continue
            if not (65.0 <= rsi <= 90.0): continue
            if not (60.0 <= rsi_htf <= 85.0): continue

            live_signals.append({
                "company": sym,
                "signal_date": row['sig_date_str'],
                "adx": round(adx, 2),
                "rsi": round(rsi, 2),
                "rsi_htf": round(rsi_htf, 2),
                "candle_range_pct": round(crange, 2),
                "signal_open": o,
                "signal_high": h,
                "signal_low": lo,
                "signal_close": float(row.get("close", 0) or 0)
            })

    except Exception as e:
        pass

print("\n" + "=" * 80)
print(f"LIVE SCAN SIGNALS ({START_DATE} to {END_DATE}) - Total: {len(live_signals)}")
print("Candle Range Formula Used: ((High - Low) / Open) * 100")
print("=" * 80)

live_signals.sort(key=lambda x: (x['signal_date'], x['company']))

for s in live_signals:
    print(f"  {s['company']:15s} | Date: {s['signal_date']} | ADX: {s['adx']:5.1f} | Range(Open): {s['candle_range_pct']:4.1f}% | RSI: {s['rsi']:4.1f} | HRSI: {s['rsi_htf']:4.1f}")
