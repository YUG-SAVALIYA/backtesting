"""
Date range chunking logic for DhanHQ intraday API.

The DhanHQ intraday API supports a maximum of 90 days per request.
This module splits arbitrary date ranges into safe sub-ranges.
"""
from datetime import date, timedelta
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)


def generate_chunks(
    from_date: date,
    to_date: date,
    chunk_size_days: int = 85,
    overlap_days: int = 1,
) -> list[tuple[date, date]]:
    """
    Split a date range into chunks safe for DhanHQ API (max 90 days each).

    Args:
        from_date: Start of the overall range (inclusive).
        to_date: End of the overall range (inclusive).
        chunk_size_days: Maximum days per chunk (default 85, buffer below 90).
        overlap_days: Overlap at chunk boundaries to prevent edge-candle loss.

    Returns:
        List of (chunk_start, chunk_end) tuples, ordered ascending.

    Example:
        generate_chunks(date(2020,1,1), date(2020,6,1)) →
        [
            (date(2020,1,1), date(2020,3,25)),  # 85 days
            (date(2020,3,25), date(2020,6,1)),   # remainder
        ]
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} must be <= to_date {to_date}")

    chunks: list[tuple[date, date]] = []
    current_start = from_date

    while current_start <= to_date:
        # End is at most chunk_size_days - 1 days after start (inclusive range)
        chunk_end = min(
            current_start + timedelta(days=chunk_size_days - 1), to_date
        )
        chunks.append((current_start, chunk_end))

        if chunk_end >= to_date:
            break

        # Next chunk starts with overlap so we don't miss boundary candles
        # overlap_days=1 → next start is 1 day before chunk_end
        next_start = chunk_end - timedelta(days=overlap_days - 1)

        # Avoid infinite loop: ensure progress
        if next_start <= current_start:
            next_start = current_start + timedelta(days=1)

        current_start = next_start

    total_days = (to_date - from_date).days + 1
    logger.info(
        f"Generated {len(chunks)} chunks for {from_date}→{to_date} "
        f"({total_days} days, chunk_size={chunk_size_days}, overlap={overlap_days})"
    )
    return chunks


def format_date(d: date) -> str:
    """Format a date as YYYY-MM-DD string for DhanHQ API."""
    return d.strftime("%Y-%m-%d")
