"""
OHLCV aggregation: 5-minute candles → Day and Week CSVs.

All aggregations are derived from the 5-minute data, never from separate API endpoints.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
OHLCV_COLS = ["datetime", "open", "high", "low", "close", "volume"]
AGGS = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def aggregate_to_day(df_5min: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate 5-minute candles into daily OHLCV candles.

    Rules:
    - Group by trading date (date component of IST datetime)
    - open = first candle open
    - high = max high
    - low = min low
    - close = last candle close
    - volume = sum
    - datetime label = midnight IST of that trading day (YYYY-MM-DD 00:00:00+05:30)
    - Ascending order by datetime

    Args:
        df_5min: DataFrame with [datetime(tz=Asia/Kolkata), open, high, low, close, volume]

    Returns:
        Daily DataFrame with same column structure, sorted ascending.
    """
    if df_5min.empty:
        logger.warning("aggregate_to_day: empty input DataFrame")
        return pd.DataFrame(columns=OHLCV_COLS)

    df = _prepare_df(df_5min)

    # Group by calendar date (in IST)
    df["_date"] = df["datetime"].dt.date

    day_df = (
        df.groupby("_date")
        .agg(AGGS)
        .reset_index()
    )

    # Build timezone-aware timestamp (targeting 05:30:00+05:30 by using UTC midnight)
    day_df["datetime"] = pd.to_datetime(day_df["_date"]).dt.tz_localize("UTC").dt.tz_convert(IST)
    day_df = day_df.drop(columns=["_date"])

    # Reorder and sort
    day_df = day_df[OHLCV_COLS].sort_values("datetime").reset_index(drop=True)

    logger.info(f"Day aggregation: {len(df_5min)} 5min rows → {len(day_df)} day rows")
    return day_df


def aggregate_to_week(df_5min: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate 5-minute candles into weekly OHLCV candles.

    Rules:
    - Group by ISO week (Monday-Sunday, W-MON frequency)
    - open = first candle open of the week
    - high = max high of the week
    - low = min low of the week
    - close = last candle close of the week
    - volume = sum of week
    - datetime label = Monday of that ISO week at midnight IST
    - Partial weeks at start/end of date range are preserved
    - Ascending order by datetime

    Args:
        df_5min: DataFrame with [datetime(tz=Asia/Kolkata), open, high, low, close, volume]

    Returns:
        Weekly DataFrame with same column structure, sorted ascending.
    """
    if df_5min.empty:
        logger.warning("aggregate_to_week: empty input DataFrame")
        return pd.DataFrame(columns=OHLCV_COLS)

    df = _prepare_df(df_5min)

    # Set datetime as index for Grouper
    df_indexed = df.set_index("datetime")

    # W-MON = week ending Sunday, label is Monday
    # Using closed='left' and label='left' to label by week start (Monday)
    week_df = (
        df_indexed.groupby(pd.Grouper(freq="W-MON", closed="left", label="left"))
        .agg(AGGS)
        .dropna(subset=["open"])  # Drop empty weeks (no data)
        .reset_index()
    )

    # Ensure datetime is tz-aware in IST and set to 05:30:00+05:30
    # We do this by normalizing to the date, localizing to UTC midnight, then converting to IST
    week_df["datetime"] = pd.to_datetime(week_df["datetime"].dt.date).dt.tz_localize("UTC").dt.tz_convert(IST)

    # ── Filter: Only Complete Weeks ─────────────────────────────────────
    # A week is complete only after Friday 3:35 PM IST.
    now = datetime.now(IST)
    is_week_finished = False
    
    if now.weekday() >= 5:  # Saturday or Sunday
        is_week_finished = True
    elif now.weekday() == 4 and now.time() >= time(15, 35):  # Friday after close
        is_week_finished = True
        
    if not is_week_finished:
        # Mon=0, Tue=1, ..., Fri=4. 
        # Current week's Monday date:
        current_monday = (now - timedelta(days=now.weekday())).date()
        # Drop rows where the Monday matches or is after the current week's Monday
        before_count = len(week_df)
        week_df = week_df[week_df["datetime"].dt.date < current_monday]
        if len(week_df) < before_count:
            logger.info("Removed incomplete current week candle (market still open or week in progress)")

    week_df = week_df[OHLCV_COLS].sort_values("datetime").reset_index(drop=True)

    logger.info(f"Week aggregation: {len(df_5min)} input rows → {len(week_df)} complete week rows")
    return week_df


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Validate and sort input DataFrame for aggregation.
    Ensures datetime is timezone-aware, sorted ascending, deduplicated.
    """
    df = df.copy()

    # Ensure datetime column is proper type
    if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
        df["datetime"] = pd.to_datetime(df["datetime"])

    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize(IST)

    df = (
        df.sort_values("datetime")
        .drop_duplicates(subset=["datetime"])
        .reset_index(drop=True)
    )

    return df
