"""
Per-symbol data fetch orchestrator.

Orchestrates the full pipeline for one symbol:
1. Generate date chunks for 5-min intraday API
2. Fetch each chunk from DhanHQ with rate limiting + retry
3. Merge 5-min chunks, deduplicate, sort → write SYMBOL_5min.csv
4. Fetch full date range Day candles from DhanHQ Historical API → write SYMBOL_daily.csv
5. Resample Day candles into Weekly → write SYMBOL_weekly.csv
6. Update job state throughout
"""
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from rsi_supertrend_backtester.data_collection.config import settings
from rsi_supertrend_backtester.data_collection.core.chunker import generate_chunks, format_date
from rsi_supertrend_backtester.data_collection.core.dhan_client import get_dhan_client
from rsi_supertrend_backtester.data_collection.models.dhan import AuthenticationError, SubscriptionError, DhanApiError
from rsi_supertrend_backtester.data_collection.models.job import SymbolStatus
from rsi_supertrend_backtester.data_collection.pipeline.aggregator import aggregate_to_week
from rsi_supertrend_backtester.data_collection.pipeline.job_manager import job_manager
from rsi_supertrend_backtester.data_collection.utils.csv_writer import write_csv
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
EMPTY_OHLCV = ["datetime", "open", "high", "low", "close", "volume"]


from rsi_supertrend_backtester.core.config import load_config
import os
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent

def _get_output_dir(job_id: str, symbol: str) -> Path:
    """Return and create the live scanner output directory for a symbol."""
    config_path = BASE_DIR / "config.json"
    backtester_config = load_config(str(config_path))
    path = backtester_config.scanner_data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_daily_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pin the datetime column to 05:30:00+05:30 for Day/Week CSVs.
    (UTC midnight = 05:30 IST)
    """
    df = df.copy()
    df["datetime"] = (
        pd.to_datetime(df["datetime"].dt.date)
        .dt.tz_localize("UTC")
        .dt.tz_convert(IST)
    )
    return (
        df.sort_values("datetime")
        .drop_duplicates(subset=["datetime"])
        .reset_index(drop=True)
    )


async def fetch_symbol(
    job_id: str,
    symbol: str,
    security_id: str,
    from_date: date,
    to_date: date,
    exchange_segment: str,
    instrument: str,
) -> None:
    """
    Execute the full fetch + CSV generation pipeline for one symbol.

    Pipeline:
    - STEP 1: Fetch 5-min candles in 85-day chunks via Intraday API
    - STEP 2: Fetch Day candles for the full range via Historical API
    - STEP 3: Derive Week candles from the Daily data
    - STEP 4: Write all three CSVs

    On AuthenticationError, raises to stop the entire job.
    On other symbol-level errors, marks symbol as failed and continues.
    """
    logger.info(f"[{symbol}] Starting fetch: {from_date}→{to_date}")

    # ── STEP 1: Skip 5-min intraday retrieval (removed by request) ────────────────────────────────
    df_merged = pd.DataFrame(columns=EMPTY_OHLCV)
    
    job_manager.update_symbol_status(
        job_id,
        symbol,
        SymbolStatus.FETCHING,
        security_id=security_id,
        total_chunks=0,
        completed_chunks=0,
    )

    client = get_dhan_client()
    request_count = 0

    # ── STEP 2: Day candles from Dhan Historical API ───────────────────────
    job_manager.update_symbol_status(job_id, symbol, SymbolStatus.AGGREGATING)
    logger.info(f"[{symbol}] Fetching Day candles from Historical API: {from_date}→{to_date}")

    def _count_hist():
        nonlocal request_count
        request_count += 1
        job_manager.increment_requests(job_id)

    df_day = pd.DataFrame(columns=EMPTY_OHLCV)
    try:
        df_day_raw = await client.fetch_historical_data(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument=instrument,
            from_date=from_date,
            to_date=to_date,
            request_counter_callback=_count_hist,
        )
        if not df_day_raw.empty:
            df_day = _normalize_daily_timestamps(df_day_raw)
            
            # ── Filter: Only Complete Days ─────────────────────────────────
            now = datetime.now(IST)
            today_date = now.date()
            
            # 1. If market is open, remove today's potentially partial candle
            if now.time() < time(15, 35):
                before_len = len(df_day)
                df_day = df_day[df_day["datetime"].dt.date < today_date]
                if len(df_day) < before_len:
                    logger.info(f"[{symbol}] Removed incomplete today's candle (market still open)")
            
            # 2. If market is CLOSED but today is MISSING from historical API (common)
            # Fetch today's intraday data and merge it as a "Day" candle
            elif now.weekday() < 5: # Monday-Friday
                has_today = any(df_day["datetime"].dt.date == today_date)
                if not has_today:
                    logger.info(f"[{symbol}] Today missing from Historical API. Fetching Intraday fallback...")
                    try:
                        from rsi_supertrend_backtester.data_collection.pipeline.aggregator import aggregate_to_day
                        df_today_intraday = await client.fetch_intraday_chunk(
                            security_id=security_id,
                            exchange_segment=exchange_segment,
                            instrument=instrument,
                            from_date=today_date,
                            to_date=today_date,
                            request_counter_callback=_count_hist
                        )
                        if not df_today_intraday.empty:
                            df_today_candle = aggregate_to_day(df_today_intraday)
                            df_day = pd.concat([df_day, df_today_candle]).sort_values("datetime").drop_duplicates(subset=["datetime"]).reset_index(drop=True)
                            logger.info(f"[{symbol}] Successfully merged today's aggregated candle from intraday data.")
                    except Exception as e:
                        logger.warning(f"[{symbol}] Failed to fetch today's intraday fallback: {e}")

            logger.info(f"[{symbol}] Day candles finalized: {len(df_day)} rows")
        else:
            logger.warning(f"[{symbol}] No Day data returned from Historical API")

    except AuthenticationError:
        raise
    except Exception as e:
        logger.warning(f"[{symbol}] Historical API failed ({e}) — Day CSV will be empty")

    # ── STEP 3: Week candles from Day data ─────────────────────────────────
    if not df_day.empty:
        df_week = aggregate_to_week(df_day)
        logger.info(f"[{symbol}] Week candles: {len(df_week)} rows (resampled from Day)")
    else:
        df_week = pd.DataFrame(columns=EMPTY_OHLCV)

    out_dir = _get_output_dir(job_id, symbol)
    rows_day = write_csv(df_day, out_dir / f"{symbol}_daily.csv")
    rows_week = write_csv(df_week, out_dir / f"{symbol}_weekly.csv")

    files = [f"{symbol}_daily.csv", f"{symbol}_weekly.csv"]

    job_manager.update_symbol_status(
        job_id,
        symbol,
        SymbolStatus.COMPLETED,
        total_rows_5min=0,
        total_rows_day=rows_day,
        total_rows_week=rows_week,
        files=files,
        error=None,
    )

    logger.info(
        f"[{symbol}] ✓ Complete — day={rows_day}, week={rows_week} rows"
    )


async def run_job(
    job_id: str,
    symbol_security_map: dict[str, str],
    from_date: date,
    to_date: date,
    exchange_segment: str,
    instrument: str,
) -> None:
    """
    Run the full pipeline for all symbols in a job.

    Processes symbols sequentially to stay within rate limits.
    Stops the entire job on authentication errors.
    Continues on per-symbol errors.
    """
    logger.info(
        f"Job {job_id} starting: {len(symbol_security_map)} symbols, "
        f"{from_date}→{to_date}"
    )

    from rsi_supertrend_backtester.data_collection.models.job import JobStatus
    job = job_manager.get_job(job_id)
    if job:
        job.status = JobStatus.RUNNING
        job_manager._save(job)

    import asyncio
    
    semaphore = asyncio.Semaphore(100) # 100 concurrent fetches
    
    async def bounded_fetch(symbol: str, security_id: str):
        # Check if job was cancelled by the user
        current_job = job_manager.get_job(job_id)
        if current_job and current_job.status == JobStatus.CANCELLED:
            logger.info(f"Job {job_id} cancelled by user. Stopping execution.")
            return

        async with semaphore:
            try:
                await fetch_symbol(
                    job_id=job_id,
                    symbol=symbol,
                    security_id=security_id,
                    from_date=from_date,
                    to_date=to_date,
                    exchange_segment=exchange_segment,
                    instrument=instrument,
                )
            except AuthenticationError as e:
                logger.error(f"Job {job_id} aborted due to auth error: {e}")
                job_manager.mark_job_failed(
                    job_id,
                    f"Authentication failed: {e}. Update DHAN_ACCESS_TOKEN in .env and restart.",
                )
                raise
                
    tasks = [bounded_fetch(symbol, security_id) for symbol, security_id in symbol_security_map.items()]
    try:
        await asyncio.gather(*tasks)
    except AuthenticationError:
        return

    # Final job status
    job = job_manager.get_job(job_id)
    if job:
        final_status = job.compute_status()
        job.status = final_status
        job_manager._save(job)
        logger.info(
            f"Job {job_id} finished: status={final_status}, "
            f"succeeded={job.completed_symbols()}, "
            f"failed={job.failed_symbols()}"
        )
