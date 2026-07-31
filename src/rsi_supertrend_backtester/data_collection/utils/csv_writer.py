"""
Deterministic CSV writer with strict format requirements.

Output contract:
- Columns: datetime, open, high, low, close, volume (exactly, lowercase)
- No index column
- UTF-8 encoding
- Datetime with +05:30 offset
- Ascending by datetime
- No duplicate datetimes
"""
from pathlib import Path
import pandas as pd
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


def write_csv(df: pd.DataFrame, path: Path) -> int:
    """
    Write DataFrame to CSV with strict format enforcement.

    Args:
        df: DataFrame with columns [datetime, open, high, low, close, volume].
            datetime must be timezone-aware (Asia/Kolkata).
        path: Output file path (parent dirs must exist).

    Returns:
        Number of rows written.

    Raises:
        ValueError: If DataFrame columns don't match required schema.
    """
    if df.empty:
        logger.warning(f"Writing empty CSV to {path}")
        _write_empty(path)
        return 0

    # Validate columns
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    # Ensure correct column order and no extra columns
    df_out = df[REQUIRED_COLUMNS].copy()

    # Ensure ascending sort + deduplication
    df_out = (
        df_out.sort_values("datetime")
        .drop_duplicates(subset=["datetime"])
        .reset_index(drop=True)
    )

    # Format datetime with explicit +05:30 offset
    df_out["datetime"] = df_out["datetime"].apply(_format_datetime)

    # Ensure numeric columns are properly typed
    for col in ["open", "high", "low", "close"]:
        df_out[col] = pd.to_numeric(df_out[col], errors="coerce")
    df_out["volume"] = pd.to_numeric(df_out["volume"], errors="coerce").astype("Int64")

    path.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(path, index=False, encoding="utf-8")

    row_count = len(df_out)
    logger.info(f"Wrote {row_count} rows → {path}")
    return row_count


def _write_empty(path: Path) -> None:
    """Write an empty CSV with correct headers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(REQUIRED_COLUMNS) + "\n")


def _format_datetime(dt) -> str:
    """Format a timezone-aware datetime as 'YYYY-MM-DD HH:MM:SS+05:30'."""
    if pd.isna(dt):
        return ""
    
    # Ensure it's a Timestamp object
    if not isinstance(dt, pd.Timestamp):
        dt = pd.to_datetime(dt)
        
    # User wants YYYY-MM-DD HH:MM:SS+05:30
    # isoformat(sep=' ') gives '2022-01-10 09:15:00+05:30'
    return dt.isoformat(sep=' ', timespec='seconds')


def validate_csv_file(path: Path) -> dict:
    """
    Validate a generated CSV file for correctness.

    Returns:
        Dict with keys: valid, row_count, errors
    """
    errors = []
    try:
        df = pd.read_csv(path)
    except Exception as e:
        return {"valid": False, "row_count": 0, "errors": [f"Cannot read CSV: {e}"]}

    # Check columns
    if list(df.columns) != REQUIRED_COLUMNS:
        errors.append(
            f"Column mismatch: got {list(df.columns)}, wanted {REQUIRED_COLUMNS}"
        )

    if not errors:
        # Check datetime ascending
        dts = pd.to_datetime(df["datetime"], utc=False)
        if not dts.is_monotonic_increasing:
            errors.append("Datetime column is not ascending")

        # Check no duplicates
        if df["datetime"].duplicated().any():
            errors.append("Duplicate datetimes found")

        # Check +05:30 offset present
        sample = df["datetime"].iloc[0] if len(df) > 0 else ""
        if "+05:30" not in str(sample):
            errors.append(f"Datetime missing +05:30 offset, got: {sample}")

    return {
        "valid": len(errors) == 0,
        "row_count": len(df),
        "errors": errors,
    }
