import re

with open('D:/AT/AI_Trading/src/rsi_supertrend_backtester/api.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = 'class ScanRequest(BaseModel):'
end_marker = '# ═══════════════════════════════════════════════════════════════════════════════'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

new_code = '''class ScanRequest(BaseModel):
    companies: str = "ALL"
    rsi_min: float = 50.0
    rsi_max: float = 90.0
    rsi_period: int = 21
    htf_rsi_min: float = 70.0
    htf_rsi_max: float = 85.0
    htf_rsi_period: int = 21
    supertrend_period: int = 21
    supertrend_multiplier: float = 1.5
    htf_supertrend_period: int = 21
    htf_supertrend_multiplier: float = 1.5
    min_cmf: float = -1.0
    min_rel_vol: float = 0.0
    min_atr: float = 0.0
    min_adx: float = 0.0
    min_candle_range: float = 0.0
    max_candle_range: float = 100.0
    target_level: float = 5.0
    target_mode: str = "fixed"
    atr_multiplier: float = 2.0
    max_stoploss_pct: float = 5.0
    entry_offset_pct: float = 0.0

@app.post("/api/live-trading/scan")
async def scan_live_trading(req: ScanRequest):
    config_path = BASE_DIR / "config.json"
    cfg = load_config(str(config_path))
    live_dir = cfg.scanner_data_dir
    
    if not live_dir.exists():
        raise HTTPException(status_code=404, detail="Live data directory not found. Please run data collection first.")
    
    if req.companies.strip().upper() == "ALL":
        scan_symbols = None
    else:
        scan_symbols = set(c.strip().strip("'\\"") for c in req.companies.split(",") if c.strip())
    
    settings = StrategySettings(
        rsi_period=req.rsi_period,
        rsi_min=0,
        rsi_max=100,
        htf_rsi_period=req.htf_rsi_period,
        htf_rsi_min=0,
        htf_rsi_max=100,
        supertrend_period=req.supertrend_period,
        supertrend_multiplier=req.supertrend_multiplier,
        htf_supertrend_period=req.htf_supertrend_period,
        htf_supertrend_multiplier=req.htf_supertrend_multiplier,
        min_cmf=-1.0,
        min_rel_vol=0,
        min_adx=0,
        min_candle_range=0,
        max_candle_range=100,
        target_mode=req.target_mode,
        atr_multiplier=req.atr_multiplier,
        max_stoploss_pct=req.max_stoploss_pct / 100.0,
        entry_offset_pct=req.entry_offset_pct
    )
    strategy = RSISupertrendStrategy(settings)

    day_files = sorted(live_dir.glob("*_daily.csv"))
    
    def process_file(df_path):
        symbol = df_path.name.replace("_daily.csv", "")
        if scan_symbols is not None and symbol not in scan_symbols:
            return None

        wf_path = live_dir / f"{symbol}_weekly.csv"

        try:
            df_day = pd.read_csv(df_path)
            df_week = pd.read_csv(wf_path) if wf_path.exists() else None

            if df_day.empty:
                return None

            def _normalize_dt(series):
                s = pd.to_datetime(series)
                if s.dt.tz is not None:
                    return s.dt.tz_convert(None)
                return s.dt.tz_localize(None)

            df_day["datetime"] = _normalize_dt(df_day["datetime"])
            if df_week is not None:
                df_week["datetime"] = _normalize_dt(df_week["datetime"])

            sig_df, _exec_df = strategy.prepare_frames(df_day, df_day, df_week)

            if sig_df.empty:
                return None

            row = sig_df.iloc[-1]
            prev_row = sig_df.iloc[-2] if len(sig_df) >= 2 else None

            in_uptrend_ltf = bool(row["in_uptrend"]) if "in_uptrend" in row else None
            ltf_just_turned_up = False
            if in_uptrend_ltf is True and prev_row is not None and "in_uptrend" in prev_row:
                prev_uptrend = bool(prev_row["in_uptrend"])
                ltf_just_turned_up = (not prev_uptrend)
            ltf_trend_str = "Uptrend" if in_uptrend_ltf else "Downtrend"
            st_ltf_val = None
            if "final_lowerband" in row and "final_upperband" in row:
                st_ltf_val = round(float(row["final_lowerband"]) if in_uptrend_ltf else float(row["final_upperband"]), 2)

            in_uptrend_htf = None
            htf_trend_str = None
            if "in_uptrend_htf" in row and pd.notna(row["in_uptrend_htf"]):
                in_uptrend_htf = bool(row["in_uptrend_htf"])
                htf_trend_str = "Uptrend" if in_uptrend_htf else "Downtrend"

            rsi_ltf = round(float(row["rsi"]), 2) if "rsi" in row and pd.notna(row["rsi"]) else None
            rsi_htf = round(float(row["rsi_htf"]), 2) if "rsi_htf" in row and pd.notna(row["rsi_htf"]) else None

            cmf_val = round(float(row["cmf"]), 4) if "cmf" in row and pd.notna(row["cmf"]) else None
            rel_vol = round(float(row["rel_vol"]), 3) if "rel_vol" in row and pd.notna(row["rel_vol"]) else None
            atr_val = round(float(row["ATR"]), 2) if "ATR" in row and pd.notna(row["ATR"]) else None
            adx_val = round(float(row["adx"]), 2) if "adx" in row and pd.notna(row["adx"]) else None
            ema_20 = round(float(row["ema_20"]), 2) if "ema_20" in row and pd.notna(row["ema_20"]) else None

            close = round(float(row["close"]), 2)
            o = round(float(row["open"]), 2)
            h = round(float(row["high"]), 2)
            lo = round(float(row["low"]), 2)

            price_vs_ema = "Above" if (ema_20 is not None and close > ema_20) else ("Below" if ema_20 is not None else None)
            candle_range_pct = round(((h - lo) / o) * 100, 3) if o > 0 else 0
            signal_date = str(row["datetime"])[:10]

            return {
                "company": symbol,
                "signal_date": signal_date,
                "close": close,
                "signal_open": o,
                "signal_high": h,
                "signal_low": lo,
                "signal_close": close,
                "entry": h,
                "Target": round(h * (1 + req.target_level / 100.0), 2),
                "Stoploss": max(lo, round(h * (1 - req.max_stoploss_pct / 100.0), 2)),
                "trend": ltf_trend_str,
                "in_uptrend_ltf": in_uptrend_ltf,
                "ltf_just_turned_up": ltf_just_turned_up,
                "supertrend_ltf": st_ltf_val,
                "in_uptrend_htf": in_uptrend_htf,
                "htf_trend": htf_trend_str,
                "supertrend_htf": None,
                "rsi": rsi_ltf,
                "rsi_HTF": rsi_htf,
                "cmf": cmf_val,
                "rel_vol": rel_vol,
                "atr": atr_val,
                "adx": adx_val,
                "ema_20": ema_20,
                "price_vs_ema20": price_vs_ema,
                "candle_range_pct": candle_range_pct,
            }
        except Exception as e:
            import logging
            logging.error(f"Error scanning {df_path.name}: {e}")
            return None

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=64) as executor:
        tasks = [loop.run_in_executor(executor, process_file, df_path) for df_path in day_files]
        raw_results = await asyncio.gather(*tasks)

    results = [r for r in raw_results if r is not None]
    results.sort(key=lambda x: x.get("company", ""))
    return results

'''

final_content = content[:start_idx] + new_code + content[end_idx:]

with open('D:/AT/AI_Trading/src/rsi_supertrend_backtester/api.py', 'w', encoding='utf-8') as f:
    f.write(final_content)
print("api.py reverted to ThreadPoolExecutor!")
