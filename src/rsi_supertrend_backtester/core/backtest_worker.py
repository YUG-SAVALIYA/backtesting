import pandas as pd
from typing import Any, Dict
import logging
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

logger = logging.getLogger(__name__)


def process_single_company_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    company = payload["company"]
    data_dir = payload["data_dir"]
    ltf = payload["ltf"]
    execution_timeframe_file_suffix = payload["execution_timeframe_file_suffix"]
    htf = payload["htf"]
    target_level = payload["target_level"]
    start_dt = pd.to_datetime(payload["start_dt"]) if payload.get("start_dt") else None
    end_dt = pd.to_datetime(payload["end_dt"]) if payload.get("end_dt") else None
    end_exclusive = pd.to_datetime(payload["end_exclusive"]) if payload.get("end_exclusive") else None
    entry_lookahead_variants = payload["entry_lookahead_variants"]
    settings_dict = payload["settings"]
    rsi_ltf_min = payload.get("rsi_ltf_min", 0.0)
    rsi_ltf_max = payload.get("rsi_ltf_max", 100.0)
    rsi_htf_min = payload.get("rsi_htf_min", 0.0)
    rsi_htf_max = payload.get("rsi_htf_max", 100.0)

    try:
        loader = MarketDataLoader(data_dir)

        # Build strategies for each variant
        strategies_by_bars = {}
        for bars in entry_lookahead_variants:
            sd = settings_dict.copy()
            sd["entry_lookahead_bars"] = bars
            strategies_by_bars[bars] = RSISupertrendStrategy(StrategySettings(**sd))

        prepare_strategy = strategies_by_bars[entry_lookahead_variants[0]]

        # ── STEP 1: Load only small daily + HTF files (memory cached) ────────
        try:
            signal_df = loader._read_csv(loader.resolve_timeframe_path(company, ltf), cache=True)
        except Exception as e:
            return {
                "company": company,
                "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
                "error": str(e),
            }

        htf_path = loader.resolve_timeframe_path(company, htf)
        try:
            htf_df = loader._read_csv(htf_path, cache=True)
        except Exception:
            htf_df = None

        # ── STEP 2: Compute indicators on daily frame only ────────────────────
        dummy_exec = pd.DataFrame(columns=["open", "high", "low", "close", "datetime"])
        signal_df, _ = prepare_strategy.prepare_frames(signal_df, dummy_exec, htf_df)

        # ── STEP 3: Pre-check — skip 5min entirely if no potential signals ────
        date_end = end_exclusive if end_exclusive is not None else end_dt
        potential_rows = signal_df[
            (signal_df["datetime"] >= start_dt) &
            (signal_df["datetime"] <= date_end) &
            (signal_df["in_uptrend"] == True)
        ]
        if len(potential_rows) > 0 and "rsi" in potential_rows.columns:
            potential_rows = potential_rows[
                (potential_rows["rsi"] >= rsi_ltf_min) & (potential_rows["rsi"] < rsi_ltf_max)
            ]
        if len(potential_rows) > 0 and "rsi_htf" in potential_rows.columns:
            potential_rows = potential_rows[
                (potential_rows["rsi_htf"] >= rsi_htf_min) & (potential_rows["rsi_htf"] < rsi_htf_max)
            ]

        if len(potential_rows) == 0:
            return {
                "company": company,
                "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
                "error": None,
            }

        # ── STEP 4: Only load large 5min file if potential signals exist ──────
        try:
            execution_df = loader._read_csv(
                loader.resolve_timeframe_path(company, execution_timeframe_file_suffix), cache=False
            )
            execution_df = execution_df.copy()
            execution_df["datetime"] = pd.to_datetime(execution_df["datetime"]).dt.tz_localize(None)
            execution_df = execution_df.set_index("datetime")
        except Exception:
            execution_df = signal_df.copy()
            if "datetime" in execution_df.columns:
                execution_df["datetime"] = pd.to_datetime(execution_df["datetime"]).dt.tz_localize(None)
                execution_df = execution_df.set_index("datetime")

        signals_by_bars = {}
        for bars, strategy in strategies_by_bars.items():
            signals = strategy.generate_signals(
                company=company,
                signal_df=signal_df,
                execution_df=execution_df,
                target_level=target_level,
            )
            filtered_signals = []
            for signal in signals:
                signal_dt = pd.to_datetime(signal.signal_time)
                in_range = signal_dt >= start_dt if start_dt else True
                if end_exclusive is not None:
                    in_range = in_range and signal_dt < end_exclusive
                elif end_dt is not None:
                    in_range = in_range and signal_dt <= end_dt
                if in_range:
                    sp = signal.to_dict()
                    sp["entry_lookahead_bars"] = bars
                    filtered_signals.append(sp)
            signals_by_bars[str(bars)] = filtered_signals

        return {"company": company, "signals_by_bars": signals_by_bars, "error": None}

    except FileNotFoundError as e:
        # Avoid spamming the terminal with tracebacks for missing symbols
        logger.warning(f"Skipping {company} - {e}")
        return {
            "company": company,
            "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
            "error": f"Symbol not found: {e}",
        }
    except Exception as e:
        # Use error instead of exception to prevent massive tracebacks from clogging the Windows console host
        logger.error(f"Error processing {company}: {e}")
        return {
            "company": company,
            "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
            "error": str(e),
        }
