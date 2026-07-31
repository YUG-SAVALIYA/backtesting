import requests
import json

url = "http://127.0.0.1:8000/api/backtest"

payload = {
    "companies": "ALL",
    "start_date": "2021-01-01",
    "end_date": "2026-12-31",
    "ltf": "Day",
    "htf": "Week",
    "supertrend_period": 21,
    "supertrend_multiplier": 1.5,
    "htf_supertrend_period": 21,
    "htf_supertrend_multiplier": 1.0,
    "rsi_ltf_period": 14,
    "rsi_ltf_min": 65.0,
    "rsi_ltf_max": 90.0,
    "rsi_htf_period": 14,
    "rsi_htf_min": 60.0,
    "rsi_htf_max": 85.0,
    "target_level": 17,
    "look_forward_limit": 1575,
    "entry_lookahead_bars": 1,
    "pre_final_max_high_lf_min": 3.0,
    "pre_final_close_lf_min": 0.0,
    "max_stoploss_pct": 5.0,
    "stoploss_mode": "signal_candle_low",
    "max_parallel": 4,
    "target_mode": "fixed",
    "atr_multiplier": 2.0,
    "entry_offset_pct": 0.0,
    "min_adx": 26.0,
    "min_candle_range": 3.0,
    "max_candle_range": 8.0,
    "trade_management_enabled": True,
    "trade_management_book_pct": 50.0,
    "trade_management_trigger_pct": 10.0,
    "trade_management_targets": [
        {"book_pct": 50.0, "trigger_pct": 10.0, "stoploss_pct": 0.0}
    ]
}

print("Sending UI Payload to API endpoint...")
res = requests.post(url, json=payload, stream=True)

final_signals = []
for line in res.iter_lines():
    if line:
        line_str = line.decode('utf-8')
        if line_str.startswith("data: "):
            try:
                data = json.loads(line_str[6:])
                if data.get("type") == "complete":
                    final_signals = data.get("signals", [])
            except Exception:
                pass

print(f"\nAPI Returned {len(final_signals)} Raw Trades from backend (before UI pre-final filter)")

# Simulate what the UI does for pre-final filtering
# preFinalSettings = {maxHighLfMin: 3.0, closeLfMin: 0.0}
max_high_lf_min = 3.0
close_lf_min = 0.0

passed = []
rejected_close = []
rejected_high = []
rejected_sl = []

for s in final_signals:
    if s.get("entry_rejected"):
        continue
    
    base_ref = s.get("original_entry") or s.get("signal_high") or s.get("entry")
    if base_ref is None:
        continue
    base_ref = float(base_ref)
    
    # Compute closeLfPct
    close_lf_pct = None
    if s.get("close_lookahead_pct") is not None:
        close_lf_pct = float(s["close_lookahead_pct"])
    if s.get("close_lookahead") is not None and base_ref > 0:
        close_lf_pct = ((float(s["close_lookahead"]) - base_ref) / base_ref) * 100
    
    # Compute maxHighLfPct
    max_high_lf_pct = None
    if s.get("max_high_lookahead_pct") is not None:
        max_high_lf_pct = float(s["max_high_lookahead_pct"])
    if s.get("max_high_lookahead") is not None and base_ref > 0:
        max_high_lf_pct = ((float(s["max_high_lookahead"]) - base_ref) / base_ref) * 100

    reasons = []
    if s.get("sl_hit_lookahead") == True:
        reasons.append("SL hit during LF")
        rejected_sl.append(s)
    if max_high_lf_pct is None or max_high_lf_pct < max_high_lf_min:
        reasons.append(f"MaxHighLF {max_high_lf_pct} < {max_high_lf_min}")
        rejected_high.append(s)
    if close_lf_pct is None or close_lf_pct < close_lf_min:
        reasons.append(f"CloseLF {close_lf_pct} < {close_lf_min}")
        rejected_close.append(s)
    
    if reasons:
        # rejected
        pass
    else:
        passed.append(s)

print(f"After UI Pre-Final Filter (H>3%, C>0%): {len(passed)} trades CONFIRMED")
print(f"  Rejected by Max High LF < 3%: {len(rejected_high)}")
print(f"  Rejected by Close LF < 0%:    {len(rejected_close)}")
print(f"  Rejected by SL hit during LF: {len(rejected_sl)}")

print(f"\nConfirmed Trades:")
for s in passed:
    sym = s.get("company", "?")
    sig_time = str(s.get("signal_time","?"))[:10]
    close_lf = None
    base_ref = float(s.get("original_entry") or s.get("signal_high") or s.get("entry") or 0)
    if s.get("close_lookahead") is not None and base_ref > 0:
        close_lf = ((float(s["close_lookahead"]) - base_ref) / base_ref) * 100
    max_h = None
    if s.get("max_high_lookahead") is not None and base_ref > 0:
        max_h = ((float(s["max_high_lookahead"]) - base_ref) / base_ref) * 100
    print(f"  {sym:15s} | {sig_time} | MaxH={max_h:.1f}% | CloseH={close_lf:.1f}%")
