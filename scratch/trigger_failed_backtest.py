import httpx
import json

payload = {
    "companies": "20MICRONS,21STCENMGM",
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

print("Sending request to http://127.0.0.1:8000/api/backtest...")
try:
    with httpx.stream("POST", "http://127.0.0.1:8000/api/backtest", json=payload, timeout=60.0) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[6:])
                if data.get("type") == "complete":
                    print("SUCCESS! Final complete message:")
                    print(json.dumps(data, indent=2))
                elif data.get("type") == "finished":
                    print(f"Finished {data.get('company')}: error={data.get('error')}")
except Exception as e:
    print("Failed to request:", e)
