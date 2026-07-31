"""Generate higher-timeframe candle CSVs from existing OHLCV files.

Examples:
    python scripts/generate_derived_candles.py --sample-size 5
    python scripts/generate_derived_candles.py --all
    python scripts/generate_derived_candles.py --symbols ABB ACC RELIANCE
"""
from __future__ import annotations

import argparse
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


IST = ZoneInfo("Asia/Kolkata")
DEFAULT_INPUT_DIR = Path("top_200_files/content/drive/MyDrive/All_Data")
DEFAULT_OUTPUT_DIR = Path("top_200_files/content/drive/MyDrive/All_Data_Derived")
OHLCV_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
INTRADAY_MARKET_OPEN = "09:15"
INTRADAY_MARKET_CLOSE = "15:30"
INTRADAY_TIMEFRAMES = {
    "15min": 15,
    "60min": 60,
    "125min": 125,
}
OUTPUT_SUFFIXES = [*INTRADAY_TIMEFRAMES, "Month"]


def read_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [col for col in OHLCV_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(missing)}")

    df = df[OHLCV_COLUMNS].copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])
    if df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize(IST)
    else:
        df["datetime"] = df["datetime"].dt.tz_convert(IST)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return (
        df.dropna(subset=["open", "high", "low", "close"])
        .sort_values("datetime")
        .drop_duplicates(subset=["datetime"], keep="last")
        .reset_index(drop=True)
    )


def aggregate_intraday(df_5min: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate intraday candles by trading day, anchored at 09:15 IST."""
    if df_5min.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    df = df_5min.copy()
    minute_of_day = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    market_open_minute = 9 * 60 + 15
    market_close_minute = 15 * 60 + 30
    minutes_from_open = minute_of_day - market_open_minute
    df = df[(minutes_from_open >= 0) & (minute_of_day < market_close_minute)].copy()
    if df.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    bucket_index = (minutes_from_open.loc[df.index] // minutes).astype("int64")
    df["_bucket_datetime"] = (
        df["datetime"].dt.normalize()
        + pd.Timedelta(minutes=market_open_minute)
        + pd.to_timedelta(bucket_index * minutes, unit="min")
    )
    out = (
        df.groupby("_bucket_datetime", sort=True)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open"])
        .reset_index()
        .rename(columns={"_bucket_datetime": "datetime"})
    )
    return out[OHLCV_COLUMNS].sort_values("datetime").reset_index(drop=True)


def aggregate_monthly(df_day: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily candles into month-start OHLCV candles."""
    if df_day.empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    indexed = df_day.set_index("datetime").sort_index()
    monthly = (
        indexed.resample("MS", label="left", closed="left")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open"])
        .reset_index()
    )
    monthly["datetime"] = (
        pd.to_datetime(monthly["datetime"].dt.date)
        .dt.tz_localize("UTC")
        .dt.tz_convert(IST)
    )
    return monthly[OHLCV_COLUMNS].sort_values("datetime").reset_index(drop=True)


def write_ohlcv_csv(df: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def discover_symbols(input_dir: Path) -> list[str]:
    symbols = {
        path.name[: -len("_5min.csv")]
        for path in input_dir.glob("*_5min.csv")
        if (input_dir / path.name.replace("_5min.csv", "_Day.csv")).exists()
    }
    return sorted(symbols)


def process_symbol(symbol: str, input_dir: Path, output_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    df_5min = read_ohlcv_csv(input_dir / f"{symbol}_5min.csv")
    df_day = read_ohlcv_csv(input_dir / f"{symbol}_Day.csv")

    for suffix, minutes in INTRADAY_TIMEFRAMES.items():
        df_out = aggregate_intraday(df_5min, minutes)
        counts[suffix] = write_ohlcv_csv(df_out, output_dir / f"{symbol}_{suffix}.csv")

    df_month = aggregate_monthly(df_day)
    counts["Month"] = write_ohlcv_csv(df_month, output_dir / f"{symbol}_Month.csv")
    return counts


def has_all_outputs(symbol: str, output_dir: Path) -> bool:
    return all((output_dir / f"{symbol}_{suffix}.csv").exists() for suffix in OUTPUT_SUFFIXES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 15, 60, 125 minute and monthly OHLCV candles.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-size", type=int, default=5, help="Number of discovered symbols to process.")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to process.")
    parser.add_argument("--all", action="store_true", help="Process every symbol with both 5min and Day files.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip symbols whose output files already exist.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    if args.symbols:
        symbols = [symbol.upper() for symbol in args.symbols]
    else:
        symbols = discover_symbols(input_dir)
        if not args.all:
            symbols = symbols[: args.sample_size]

    if not symbols:
        print("No symbols found to process.")
        return 1

    original_count = len(symbols)
    if args.skip_existing:
        symbols = [symbol for symbol in symbols if not has_all_outputs(symbol, output_dir)]
        skipped_count = original_count - len(symbols)
        print(f"Skipped complete symbols: {skipped_count}")

    if not symbols:
        print("No remaining symbols to process.")
        return 0

    print(f"Input : {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Symbols: {', '.join(symbols)}")

    for symbol in symbols:
        counts = process_symbol(symbol, input_dir, output_dir)
        print(
            f"{symbol}: "
            f"15min={counts['15min']}, "
            f"60min={counts['60min']}, "
            f"125min={counts['125min']}, "
            f"Month={counts['Month']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
