"""
Diagnose:
1. Which files cause [Errno 22] Invalid argument
2. How large each 5min file is
3. Which files are missing entirely
"""
import sys
import json
import time
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader

with open("output/backtest_2026-06-19_08-50-45_2114stocks.json") as f:
    failed = json.load(f)

companies = failed["settings"]["companies"].split(",")
data_dir = Path("F:/Data")

missing_day = []
missing_week = []
missing_5min = []
errno22 = []
large_files = []  # files > 200MB
slow_reads = []   # files that take > 3s to read

print(f"Checking {len(companies)} companies...\n")

for i, company in enumerate(companies):
    day_path = data_dir / f"{company}_Day.csv"
    week_path = data_dir / f"{company}_Week.csv"
    min5_path = data_dir / f"{company}_5min.csv"

    if not day_path.exists():
        missing_day.append(company)
        continue

    if not week_path.exists():
        missing_week.append(company)

    if not min5_path.exists():
        missing_5min.append(company)
        continue

    # Check file size
    size_mb = min5_path.stat().st_size / 1024 / 1024
    if size_mb > 200:
        large_files.append((company, round(size_mb, 1)))

    # Try reading the day file to detect errno 22
    try:
        t0 = time.perf_counter()
        df = pd.read_csv(day_path)
        elapsed = time.perf_counter() - t0
        if elapsed > 1.0:
            slow_reads.append((company, "Day", round(elapsed, 2)))
    except Exception as e:
        errno22.append((company, "Day", str(e)))

    if i % 200 == 0:
        print(f"  Progress: {i}/{len(companies)}")

print(f"\n=== RESULTS ===")
print(f"Missing _Day.csv:  {len(missing_day)} companies")
print(f"Missing _Week.csv: {len(missing_week)} companies")
print(f"Missing _5min.csv: {len(missing_5min)} companies")
print(f"Errno 22 errors:   {len(errno22)} companies")
print(f"Large 5min files (>200MB): {len(large_files)}")
print(f"Slow day reads (>1s): {len(slow_reads)}")

if errno22:
    print(f"\nErrno 22 samples:")
    for c, f, e in errno22[:10]:
        print(f"  {c} ({f}): {e}")

if large_files:
    print(f"\nLargest 5min files:")
    for c, mb in sorted(large_files, key=lambda x: -x[1])[:10]:
        print(f"  {c}: {mb} MB")

if missing_day[:20]:
    print(f"\nMissing Day samples: {missing_day[:20]}")

if missing_5min[:20]:
    print(f"\nMissing 5min samples: {missing_5min[:20]}")
