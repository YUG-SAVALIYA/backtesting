import httpx
import json
import time

# Load the companies list from config
with open("config.json", "r") as f:
    cfg = json.load(f)

# Use ALL companies from the previous failed backtest - reconstruct from 2114stocks file
with open("output/backtest_2026-06-19_08-50-45_2114stocks.json", "r") as f:
    failed = json.load(f)

companies_str = failed["settings"]["companies"]
companies = companies_str.split(",")
print(f"Total companies: {len(companies)}")

payload = {
    "companies": companies_str,
    "start_date": "2021-01-01",
    "end_date": "2025-12-31",
    "ltf": "Day",
    "htf": "Week",
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 14,
    "htf_supertrend_multiplier": 1.0,
    "rsi_ltf_period": 14,
    "rsi_ltf_min": 50.0,
    "rsi_ltf_max": 90.0,
    "rsi_htf_period": 14,
    "rsi_htf_min": 65.0,
    "rsi_htf_max": 85.0,
    "target_level": 20,
    "look_forward_limit": 1575,
    "entry_lookahead_bars": 1,
    "max_stoploss_pct": 5.0,
    "stoploss_mode": "signal_candle_low",
    "max_parallel": 128,
    "target_mode": "fixed",
    "atr_multiplier": 2.0,
    "entry_offset_pct": 0.0,
    "trade_management_enabled": False,
    "trade_management_book_pct": 50.0,
    "trade_management_trigger_pct": 10.0,
    "trade_management_targets": [{"book_pct": 50.0, "trigger_pct": 10.0, "stoploss_pct": 0.0}]
}

print("Starting full backtest run...")
t_start = time.perf_counter()
completed = 0
errors = []
last_print = time.perf_counter()

try:
    with httpx.stream("POST", "http://127.0.0.1:8000/api/backtest", json=payload, timeout=600.0) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            evt_type = data.get("type")

            if evt_type == "finished":
                completed += 1
                err = data.get("error")
                if err:
                    errors.append({"company": data.get("company"), "error": err})

                now = time.perf_counter()
                if now - last_print > 5:  # print every 5 seconds
                    elapsed = now - t_start
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"  [{elapsed:.1f}s] Completed: {completed}/{len(companies)} | Rate: {rate:.1f}/s | Errors so far: {len(errors)}")
                    last_print = now

            elif evt_type == "complete":
                elapsed = time.perf_counter() - t_start
                metrics = data.get("metrics", {})
                print(f"\n=== DONE in {elapsed:.1f}s ===")
                print(f"Total signals: {metrics.get('total', 0)}")
                print(f"Errors: {metrics.get('error_count', 0)}")
                if errors:
                    print(f"\nFirst 10 errors:")
                    for e in errors[:10]:
                        print(f"  {e['company']}: {e['error']}")
                break

except Exception as ex:
    elapsed = time.perf_counter() - t_start
    print(f"\n!!! EXCEPTION after {elapsed:.1f}s, completed={completed}")
    print(f"Exception: {type(ex).__name__}: {ex}")
    if errors:
        print(f"Last errors seen:")
        for e in errors[-5:]:
            print(f"  {e['company']}: {e['error']}")
