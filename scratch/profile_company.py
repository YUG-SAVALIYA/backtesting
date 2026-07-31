"""Profile exactly where time is spent per company."""
import sys, time
import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

loader = MarketDataLoader("F:/Data")
settings = StrategySettings(rsi_period=14, rsi_min=50.0, rsi_max=90.0, htf_rsi_period=14,
    htf_rsi_min=65.0, htf_rsi_max=85.0, supertrend_period=21, supertrend_multiplier=1.5,
    htf_supertrend_period=14, htf_supertrend_multiplier=1.0)
strategy = RSISupertrendStrategy(settings)
company = "ADANIENT"

print(f"Profiling {company}...\n")
times = {}

t = time.perf_counter(); sig_df = loader._read_csv(loader.data_dir / f"{company}_Day.csv", cache=False); times["read_day_cold"] = time.perf_counter()-t
t = time.perf_counter(); sig_df = loader._read_csv(loader.data_dir / f"{company}_Day.csv", cache=True); times["read_day_warm"] = time.perf_counter()-t
t = time.perf_counter(); sig_df2 = loader._read_csv(loader.data_dir / f"{company}_Day.csv", cache=True); times["read_day_cached"] = time.perf_counter()-t

htf_path = loader.data_dir / f"{company}_Week.csv"
t = time.perf_counter(); htf_df = loader._read_csv(htf_path, cache=True); times["read_week_cold"] = time.perf_counter()-t
t = time.perf_counter(); htf_df = loader._read_csv(htf_path, cache=True); times["read_week_cached"] = time.perf_counter()-t

dummy_exec = pd.DataFrame(columns=["open","high","low","close","datetime"])
t = time.perf_counter(); prepared_sig, _ = strategy.prepare_frames(sig_df, dummy_exec, htf_df); times["prepare_frames"] = time.perf_counter()-t

start_dt = pd.to_datetime("2021-01-01"); end_dt = pd.to_datetime("2025-12-31")
t = time.perf_counter()
pr = prepared_sig[(prepared_sig["datetime"]>=start_dt)&(prepared_sig["datetime"]<=end_dt)&(prepared_sig["in_uptrend"]==True)]
if "rsi" in pr.columns: pr = pr[(pr["rsi"]>=50.0)&(pr["rsi"]<90.0)]
if "rsi_htf" in pr.columns: pr = pr[(pr["rsi_htf"]>=65.0)&(pr["rsi_htf"]<85.0)]
times["signal_check"] = time.perf_counter()-t

print(f"Has potential: {len(pr)>0}")
if len(pr) > 0:
    t = time.perf_counter(); exec_df = loader._read_csv(loader.data_dir / f"{company}_5min.csv", cache=False); times["read_5min"] = time.perf_counter()-t
    exec_df = exec_df.copy(); exec_df["datetime"] = pd.to_datetime(exec_df["datetime"]).dt.tz_localize(None); exec_df = exec_df.set_index("datetime")
    t = time.perf_counter(); sigs = strategy.generate_signals(company, prepared_sig, exec_df, 20); times["generate_signals"] = time.perf_counter()-t
    print(f"Signals: {len(sigs)}")

print("\n=== TIMING BREAKDOWN ===")
for k, v in times.items():
    print(f"  {k:25s}: {v*1000:.1f} ms")
print(f"\n  TOTAL (cold): {sum(times.values())*1000:.1f} ms")
print(f"  TOTAL (cached): {(times.get('read_day_cached',0)+times.get('read_week_cached',0)+times.get('prepare_frames',0)+times.get('signal_check',0)+times.get('read_5min',0)+times.get('generate_signals',0))*1000:.1f} ms")
