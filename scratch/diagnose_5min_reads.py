"""
Time the reading of each company's 5min CSV to find which one causes the massive stall.
Also check datetime parsing (which is where the actual slowness is).
"""
import sys
import json
import time
import pandas as pd
from pathlib import Path

with open("output/backtest_2026-06-19_08-50-45_2114stocks.json") as f:
    failed = json.load(f)

companies = failed["settings"]["companies"].split(",")
data_dir = Path("F:/Data")

slow_5min = []   # files that take > 2s to read + parse
errno22_5min = []
THRESHOLD = 2.0  # seconds

print(f"Timing 5min reads for {len(companies)} companies (threshold={THRESHOLD}s)...")
print("Will print any file that takes longer than 2 seconds...\n")

for i, company in enumerate(companies):
    min5_path = data_dir / f"{company}_5min.csv"
    if not min5_path.exists():
        continue

    try:
        t0 = time.perf_counter()
        # Replicate EXACTLY what data_loader does
        df = pd.read_csv(min5_path)
        t_read = time.perf_counter() - t0

        # Now parse datetime - this is where it can hang
        t1 = time.perf_counter()
        df["datetime"] = pd.to_datetime(df["datetime"].str[:19], format="%Y-%m-%d %H:%M:%S")
        t_parse = time.perf_counter() - t1

        total = t_read + t_parse
        size_mb = min5_path.stat().st_size / 1024 / 1024

        if total > THRESHOLD:
            slow_5min.append((company, round(t_read, 2), round(t_parse, 2), round(size_mb, 1)))
            print(f"  SLOW [{i}] {company}: read={t_read:.2f}s parse={t_parse:.2f}s size={size_mb:.1f}MB rows={len(df)}")

    except Exception as e:
        errno22_5min.append((company, str(e)))
        print(f"  ERROR [{i}] {company}: {e}")

    if i % 300 == 0 and i > 0:
        print(f"  Progress: {i}/{len(companies)} checked so far...")

print(f"\n=== RESULTS ===")
print(f"Slow reads (>{THRESHOLD}s): {len(slow_5min)}")
print(f"Errors during 5min read: {len(errno22_5min)}")

if slow_5min:
    print("\nSlow files:")
    for c, tr, tp, mb in sorted(slow_5min, key=lambda x: -(x[1]+x[2])):
        print(f"  {c}: read={tr}s parse={tp}s size={mb}MB")

if errno22_5min:
    print("\nError files:")
    for c, e in errno22_5min[:20]:
        print(f"  {c}: {e}")
