"""
DhanHQ instrument master management.

Downloads, caches, and queries the DhanHQ instrument master CSV for
symbol-to-securityId resolution.

Instrument master URL:
    https://images.dhan.co/api-data/api-scrip-master-detailed.csv

Key columns:
    SECURITY_ID             → securityId for API requests
    SYMBOL_NAME             → trading symbol (e.g., RELIANCE)
    SEGMENT                 → E=Equity, D=Derivatives
    INSTRUMENT_TYPE         → EQUITY, FUTSTK, OPTSTK, etc.
    EXCH_ID                 → NSE, BSE, MCX, etc.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from rsi_supertrend_backtester.data_collection.config import settings
from rsi_supertrend_backtester.data_collection.models.job import SymbolCandidate
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)

# In-memory cache per process
_master_df: Optional[pd.DataFrame] = None
_last_loaded: Optional[datetime] = None
_nse_eq_cache: dict[str, SymbolCandidate] = {}
_tick_cache:   dict[str, float] = {}   # security_id → tick_size

# Exchange segment → EXM_EXCH_ID + SEGMENT mapping
SEGMENT_MAP = {
    "NSE_EQ": {"exch": "NSE", "segment": "E"},
    "BSE_EQ": {"exch": "BSE", "segment": "E"},
    "NSE_FNO": {"exch": "NSE", "segment": "D"},
    "BSE_FNO": {"exch": "BSE", "segment": "D"},
}


class InstrumentMaster:
    """Singleton-style instrument master with local CSV caching."""

    def __init__(self):
        self._cache_path = settings.cache_dir / "instrument_master.csv"
        self._meta_path = settings.cache_dir / "instrument_master_meta.json"

    def _normalize_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pre-compute normalized columns for fast lookups."""
        global _nse_eq_cache
        df["_N_SYMBOL"] = df["SYMBOL_NAME"].astype(str).str.upper().str.strip()
        df["_N_UNDERLYING"] = df["UNDERLYING_SYMBOL"].astype(str).str.upper().str.strip()
        df["_N_EXCH"] = df["EXCH_ID"].astype(str).str.upper()
        df["_N_SEGMENT"] = df["SEGMENT"].astype(str).str.upper()
        df["_N_INSTRUMENT"] = df["INSTRUMENT"].astype(str).str.upper()
        
        # Build O(1) cache for NSE_EQ Equities
        _nse_eq_cache.clear()
        nse_eq_df = df[
            (df["_N_EXCH"] == "NSE") & 
            (df["_N_SEGMENT"] == "E") & 
            (df["_N_INSTRUMENT"] == "EQUITY")
        ]
        
        for _, row in nse_eq_df.iterrows():
            sym1 = row["_N_SYMBOL"]
            sym2 = row["_N_UNDERLYING"]
            candidate = SymbolCandidate(
                security_id=str(row.get("SECURITY_ID", "")),
                trading_symbol=str(row.get("SYMBOL_NAME", "")),
                exchange=str(row.get("EXCH_ID", "")),
                instrument_type=str(row.get("INSTRUMENT", "")),
            )
            if sym1 and sym1 not in _nse_eq_cache:
                _nse_eq_cache[sym1] = candidate
            if sym2 and sym2 not in _nse_eq_cache:
                _nse_eq_cache[sym2] = candidate

        # Build tick-size lookup: security_id → TICK_SIZE
        _tick_cache.clear()
        if "TICK_SIZE" in df.columns:
            for _, row in nse_eq_df.iterrows():
                sid = str(row.get("SECURITY_ID", ""))
                tick = row.get("TICK_SIZE")
                if sid and tick and float(tick) > 0:
                    _tick_cache[sid] = float(tick)

        logger.info(f"Built O(1) lookup cache for {len(_nse_eq_cache)} NSE Equities, {len(_tick_cache)} tick sizes")
        return df

    async def get_dataframe(self) -> pd.DataFrame:
        """Return the instrument master DataFrame, refreshing if stale."""
        global _master_df, _last_loaded

        if _master_df is not None and _last_loaded is not None:
            age = datetime.utcnow() - _last_loaded
            if age < timedelta(hours=settings.instrument_master_ttl_hours):
                return _master_df

        # Try local cache first
        if self._is_cache_fresh():
            logger.info("Loading instrument master from local cache")
            _master_df = self._normalize_df(self._load_from_cache())
            _last_loaded = datetime.utcnow()
            return _master_df

        # Download fresh copy
        logger.info("Downloading fresh instrument master CSV")
        df = await self._download()
        self._save_to_cache(df)
        _master_df = self._normalize_df(df)
        _last_loaded = datetime.utcnow()
        return _master_df

    def _is_cache_fresh(self) -> bool:
        """Check if the local cache file exists and is within TTL."""
        if not self._cache_path.exists() or not self._meta_path.exists():
            return False
        try:
            meta = json.loads(self._meta_path.read_text())
            cached_at = datetime.fromisoformat(meta["cached_at"])
            age = datetime.utcnow() - cached_at
            return age < timedelta(hours=settings.instrument_master_ttl_hours)
        except Exception:
            return False

    def _load_from_cache(self) -> pd.DataFrame:
        """Load instrument master from local cache file."""
        df = pd.read_csv(self._cache_path, low_memory=False)
        logger.info(f"Loaded {len(df)} instruments from cache")
        return df

    def _save_to_cache(self, df: pd.DataFrame) -> None:
        """Save instrument master DataFrame to local cache."""
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(self._cache_path, index=False)
        meta = {"cached_at": datetime.utcnow().isoformat(), "row_count": len(df)}
        self._meta_path.write_text(json.dumps(meta, indent=2))
        logger.info(f"Cached {len(df)} instruments to {self._cache_path}")

    async def _download(self) -> pd.DataFrame:
        """Download instrument master CSV from DhanHQ CDN."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(settings.instrument_master_url)
            response.raise_for_status()

        # Parse CSV
        import io
        df = pd.read_csv(io.StringIO(response.text), low_memory=False)
        logger.info(f"Downloaded {len(df)} instruments from DhanHQ")
        return df

    def get_tick_size(self, security_id: str) -> float:
        """Return the tick size for a given security_id.
        Looks up the in-memory cache built from the instrument master.
        Dhan stores TICK_SIZE in paise (e.g. 5.0 for 5 paise = 0.05 INR).
        Falls back to 0.05 (NSE equity default) if not found.
        """
        raw_tick = _tick_cache.get(str(security_id))
        if raw_tick is not None:
            return raw_tick / 100.0
        return 0.05

    async def resolve_symbol(
        self,
        symbol: str,
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
    ) -> tuple[list[SymbolCandidate], bool]:
        """
        Resolve a trading symbol to one or more security ID candidates.

        Resolution order:
        1. exact match in preferred exchange_segment + instrument
        2. fall back to preferred exchange, any instrument
        3. fall back to all exchanges

        Returns:
            (candidates, is_exact_match)
            - If 1 candidate and is_exact_match=True: unambiguous
            - If >1 candidates: ambiguous, return for user selection
            - If 0 candidates: not found
        """
        df = await self.get_dataframe()
        symbol_upper = symbol.upper().strip()
        
        # O(1) Fast path for NSE_EQ Equities
        if exchange_segment == "NSE_EQ" and instrument == "EQUITY":
            global _nse_eq_cache
            if symbol_upper in _nse_eq_cache:
                return ([_nse_eq_cache[symbol_upper]], True)

        seg_info = SEGMENT_MAP.get(exchange_segment, {"exch": "NSE", "segment": "E"})
        preferred_exch = seg_info["exch"]
        preferred_seg = seg_info["segment"]

        # Helper to build candidate list
        def to_candidates(rows: pd.DataFrame) -> list[SymbolCandidate]:
            results = []
            for _, row in rows.iterrows():
                results.append(
                    SymbolCandidate(
                        security_id=str(row.get("SECURITY_ID", "")),
                        trading_symbol=str(row.get("SYMBOL_NAME", "")),
                        exchange=str(row.get("EXCH_ID", "")),
                        instrument_type=str(row.get("INSTRUMENT", "")),
                    )
                )
            return results

        # Normalize symbol columns (now just reference the pre-computed ones)
        sym_col = df["_N_SYMBOL"]
        under_col = df["_N_UNDERLYING"]

        # Pass 1: preferred exchange + preferred segment + requested instrument
        mask = (
            ((sym_col == symbol_upper) | (under_col == symbol_upper))
            & (df["_N_EXCH"] == preferred_exch)
            & (df["_N_SEGMENT"] == preferred_seg.upper())
            & (df["_N_INSTRUMENT"] == instrument.upper())
        )
        matched = df[mask]

        if len(matched) == 1:
            return to_candidates(matched), True

        if len(matched) > 1:
            return to_candidates(matched), False

        # Pass 2: preferred exchange, any instrument, equity segment
        mask2 = (
            ((sym_col == symbol_upper) | (under_col == symbol_upper))
            & (df["_N_EXCH"] == preferred_exch)
            & (df["_N_SEGMENT"] == preferred_seg.upper())
        )
        matched2 = df[mask2]

        if len(matched2) == 1:
            return to_candidates(matched2), True
        if len(matched2) > 1:
            return to_candidates(matched2), False

        # Pass 3: all exchanges matching symbol
        mask3 = ((sym_col == symbol_upper) | (under_col == symbol_upper))
        matched3 = df[mask3]

        if len(matched3) >= 1:
            return to_candidates(matched3), len(matched3) == 1

        return [], False

    async def resolve_symbols_batch(
        self,
        symbols: list[str],
        exchange_segment: str = "NSE_EQ",
        instrument: str = "EQUITY",
    ) -> tuple[dict, dict, list]:
        """
        Resolve multiple symbols at once.

        Returns:
            (resolved, ambiguous, not_found)
            - resolved: {symbol: SymbolCandidate}
            - ambiguous: {symbol: [SymbolCandidate, ...]}
            - not_found: [symbol, ...]
        """
        resolved = {}
        ambiguous = {}
        not_found = []

        for symbol in symbols:
            candidates, is_exact = await self.resolve_symbol(
                symbol, exchange_segment, instrument
            )
            if not candidates:
                not_found.append(symbol)
                logger.warning(f"Symbol not found: {symbol}")
            elif is_exact and len(candidates) == 1:
                resolved[symbol] = candidates[0]
                logger.debug(
                    f"Resolved {symbol} → securityId={candidates[0].security_id}"
                )
            else:
                ambiguous[symbol] = candidates
                logger.info(f"Ambiguous symbol {symbol}: {len(candidates)} candidates")

        return resolved, ambiguous, not_found


# Module-level singleton instance
instrument_master = InstrumentMaster()
