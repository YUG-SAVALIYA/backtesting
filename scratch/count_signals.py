"""Count how many companies have potential signals (before loading 5min)."""
import sys, time
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings
import json

with open("output/backtest_2026-06-19_08-50-45_2114stocks.json") as f:
    failed = json.load(f)
companies = failed["settings"]["companies"].split(",")

loader = MarketDataLoader("F:/Data")
settings = StrategySettings(rsi_period=14, rsi_min=50.0, rsi_max=90.0, htf_rsi_period=14,
    htf_rsi_min=65.0, htf_rsi_max=85.0, supertrend_period=21, supertrend_multiplier=1.5,
    htf_supertrend_period=14, htf_supertrend_multiplier=1.0)
strategy = RSISupertrendStrategy(settings)
start_dt, end_dt = pd.to_datetime("2021-01-01"), pd.to_datetime("2025-12-31")
dummy_exec = pd.DataFrame(columns=["open","high","low","close","datetime"])

has_signals, no_signals, missing, errors = 0, 0, 0, 0
t0 = time.perf_counter()

for i, company in enumerate(companies):
    day_path = loader.data_dir / f"{company}_Day.csv"
    if not day_path.exists():
        missing += 1; continue
    try:
        sig_df = loader._read_csv(day_path, cache=True)
        htf_path = loader.data_dir / f"{company}_Week.csv"
        htf_df = loader._read_csv(htf_path, cache=True) if htf_path.exists() else None
        sig_df, _ = strategy.prepare_frames(sig_df, dummy_exec, htf_df)
        pr = sig_df[(sig_df["datetime"]>=start_dt)&(sig_df["datetime"]<=end_dt)&(sig_df["in_uptrend"]==True)]
        if "rsi" in pr.columns: pr = pr[(pr["rsi"]>=50)&(pr["rsi"]<90)]
        if "rsi_htf" in pr.columns: pr = pr[(pr["rsi_htf"]>=65)&(pr["rsi_htf"]<85)]
        if len(pr) > 0: has_signals += 1
        else: no_signals += 1
    except Exception as e:
        errors += 1

elapsed = time.perf_counter() - t0
total_processed = has_signals + no_signals
print(f"\n=== Signal Pre-Check Results (all {len(companies)} companies) ===")
print(f"  Time taken (serial):  {elapsed:.1f}s")
print(f"  Has potential signals: {has_signals} ({100*has_signals/total_processed:.1f}%)")
print(f"  No signals (SKIP 5min): {no_signals} ({100*no_signals/total_processed:.1f}%)")
print(f"  Missing Day file: {missing}")
print(f"  Errors: {errors}")
print(f"\n  => Only {has_signals} companies need 5min loading (~{has_signals*140:.0f}ms)")
print(f"  => {no_signals} companies skip 5min entirely (~{no_signals*22:.0f}ms saved)")
