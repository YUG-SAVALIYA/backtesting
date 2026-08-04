from __future__ import annotations

from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text


REQUIRED_COLS = {"datetime", "open", "high", "low", "close"}

class DataValidationError(Exception):
    pass

class MarketDataLoader:
    _cache = {}

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def resolve_timeframe_path(self, symbol: str, suffix: str) -> Path:
        norm = {
            "day": "daily", "daily": "daily", "day.csv": "daily", "daily.csv": "daily",
            "week": "weekly", "weekly": "weekly", "week.csv": "weekly", "weekly.csv": "weekly",
            "month": "monthly", "monthly": "monthly", "month.csv": "monthly", "monthly.csv": "monthly",
            "5min": "5min", "5m": "5min"
        }
        s = suffix.lower().strip()
        mapped_suffix = norm.get(s, s)
        
        return self.data_dir / f"{symbol}_{mapped_suffix}.csv"

    def _read_csv(self, path: Path, cache: bool = True) -> pd.DataFrame:
        path = Path(path)
        path_key = str(path.resolve())
        mtime = path.stat().st_mtime if path.exists() else 0
        
        if cache and path_key in MarketDataLoader._cache:
            cached_df, cached_mtime = MarketDataLoader._cache[path_key]
            if not path.exists() or cached_mtime == mtime:
                return cached_df.copy()

        symbol = path.stem.split('_')[0]

        if not path.exists():
            raise FileNotFoundError(f"Missing local file for {symbol}: {path}")
            
        try:
            # Fast multi-threaded PyArrow CSV parsing (26x faster than default engine)
            df = pd.read_csv(
                path,
                engine='pyarrow',
                dtype={'open': 'float64', 'high': 'float64', 'low': 'float64', 'close': 'float64', 'volume': 'float64'}
            )
        except Exception:
            try:
                df = pd.read_csv(path, parse_dates=['datetime'], date_format='%Y-%m-%d %H:%M:%S', engine='c')
            except Exception:
                df = pd.read_csv(path)
        
        # If no header (5m fix)
        if 'date' not in df.columns and 'datetime' not in df.columns:
            try:
                df = pd.read_csv(
                    path,
                    header=None,
                    names=['datetime','open','high','low','close','volume'],
                    engine='pyarrow',
                    dtype={'open': 'float64', 'high': 'float64', 'low': 'float64', 'close': 'float64', 'volume': 'float64'}
                )
            except Exception:
                df = pd.read_csv(path, header=None, names=['datetime','open','high','low','close','volume'])
        
        if 'date' in df.columns:
            df.rename(columns={'date': 'datetime'}, inplace=True)
            
        missing = REQUIRED_COLS - set(df.columns)
        if missing:
            raise DataValidationError(f"Missing columns in {path.name}: {sorted(missing)}")
        
        if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            raw_dt = df["datetime"].astype(str).str[:19]
            parsed = pd.to_datetime(raw_dt, format="%Y-%m-%d %H:%M:%S", errors="coerce")
            bad_mask = parsed.isna()
            if bad_mask.any():
                parsed[bad_mask] = pd.to_datetime(raw_dt[bad_mask], errors="coerce")
            df["datetime"] = parsed
        elif getattr(df["datetime"].dt, "tz", None) is not None:
            df["datetime"] = df["datetime"].dt.tz_localize(None)
        df = df.dropna(subset=["datetime"])
        if not df["datetime"].is_monotonic_increasing:
            df = df.sort_values("datetime").reset_index(drop=True)
            
        if cache:
            if len(MarketDataLoader._cache) > 500:
                first_key = next(iter(MarketDataLoader._cache))
                MarketDataLoader._cache.pop(first_key, None)
            MarketDataLoader._cache[path_key] = (df, mtime)
        return df.copy()

    def load_symbol_frames(self, symbol: str, signal_suffix: str, execution_suffix: str, daily_suffix: str):
        signal_df = self._read_csv(self.resolve_timeframe_path(symbol, signal_suffix), cache=True)
        
        try:
            execution_df = self._read_csv(self.resolve_timeframe_path(symbol, execution_suffix), cache=False)
        except Exception:
            # For 5-minute data, we allow it to fail silently if missing
            execution_df = pd.DataFrame()
            
        daily_path = self.resolve_timeframe_path(symbol, daily_suffix)
        daily_df = self._read_csv(daily_path, cache=True) if daily_path.exists() or daily_path.name.endswith('daily.csv') else None
        
        return signal_df, execution_df, daily_df

