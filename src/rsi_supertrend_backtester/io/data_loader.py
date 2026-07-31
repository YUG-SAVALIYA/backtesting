from __future__ import annotations

from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..db import engine

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
        
        if mapped_suffix == "5min":
            hist_dir = Path(r"C:\Users\Yug\Desktop\rsi\data\5min_historical")
            if (hist_dir / f"{symbol}_5m.csv").exists():
                return hist_dir / f"{symbol}_5m.csv"
            if (hist_dir / f"{symbol}_5min.csv").exists():
                return hist_dir / f"{symbol}_5min.csv"
        
        path1 = self.data_dir / f"{symbol}_{mapped_suffix}.csv"
        return path1

    def _read_csv(self, path: Path, cache: bool = True) -> pd.DataFrame:
        path_key = str(path.resolve())
        mtime = path.stat().st_mtime if path.exists() else 0
        
        if cache and path_key in MarketDataLoader._cache:
            cached_df, cached_mtime = MarketDataLoader._cache[path_key]
            if not path.exists() or cached_mtime == mtime:
                return cached_df.copy()

        symbol = path.stem.split('_')[0]
        mapped_suffix = path.name.split('_')[-1].replace('.csv', '').lower()

        df = None
        
        if mapped_suffix in ['daily', 'weekly', 'monthly']:
            # Fetch daily data from postgres!
            query = "SELECT datetime, open, high, low, close, volume FROM market_candles_cleaned WHERE symbol = %(symbol)s ORDER BY datetime ASC"
            df = pd.read_sql(query, engine, params={"symbol": symbol})
            
            if df.empty:
                raise ValueError(f"No daily data found in DB for {symbol}")
                
            # Convert datetime to pandas datetime
            raw_dt = df["datetime"].astype(str).str[:19]
            parsed = pd.to_datetime(raw_dt, format="%Y-%m-%d", errors="coerce")
            bad_mask = parsed.isna()
            if bad_mask.any():
                parsed[bad_mask] = pd.to_datetime(raw_dt[bad_mask], errors="coerce")
            df["datetime"] = parsed
            df = df.dropna(subset=["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
            
            if mapped_suffix == 'weekly':
                daily_df = df.set_index("datetime")
                df = daily_df.resample("W-FRI").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                }).dropna().reset_index()
                df["symbol"] = symbol

        else:
            # Fallback for 5min and others (loading from file)
            if not path.exists():
                raise FileNotFoundError(f"Missing local CSV file for {symbol}: {path}")
                
            df = pd.read_csv(path)
            
            # If no header (5m fix)
            if 'date' not in df.columns and 'datetime' not in df.columns:
                df = pd.read_csv(path, header=None, names=['datetime','open','high','low','close','volume'])
            
            if 'date' in df.columns:
                df.rename(columns={'date': 'datetime'}, inplace=True)
                
            missing = REQUIRED_COLS - set(df.columns)
            if missing:
                raise DataValidationError(f"Missing columns in {path.name}: {sorted(missing)}")
            
            raw_dt = df["datetime"].astype(str).str[:19]
            parsed = pd.to_datetime(raw_dt, format="%Y-%m-%d %H:%M:%S", errors="coerce")
            bad_mask = parsed.isna()
            if bad_mask.any():
                parsed[bad_mask] = pd.to_datetime(raw_dt[bad_mask], errors="coerce")
            df["datetime"] = parsed
            df = df.dropna(subset=["datetime"])
            df = df.sort_values("datetime").reset_index(drop=True)
        
        if cache:
            if len(MarketDataLoader._cache) > 300:
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
