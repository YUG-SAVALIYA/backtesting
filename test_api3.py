import urllib.request
import json

payload = {
    "ltf": "daily",
    "htf": "weekly",
    "start_date": "2021-01-01",
    "end_date": "2026-12-31",
    "companies": ["360ONE"],
    "rsi_ltf_period": 21,
    "rsi_ltf_min": 50,
    "rsi_ltf_max": 90,
    "rsi_htf_period": 21,
    "rsi_htf_min": 65,
    "rsi_htf_max": 85,
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 21,
    "htf_supertrend_multiplier": 1.5,
    "max_stoploss_pct": 5,
    "target_level": 17,
    "target_mode": "fixed",
    "atr_multiplier": 2.0,
    "entry_offset_pct": 0,
    "trade_management_enabled": False,
    "trade_management_book_pct": 0,
    "trade_management_trigger_pct": 0,
    "trade_management_targets": []
}

req = urllib.request.Request("http://127.0.0.1:8000/api/backtest", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}); response = urllib.request.urlopen(req)
for line in response:
    if line.strip():
        print(line.decode("utf-8").strip())
