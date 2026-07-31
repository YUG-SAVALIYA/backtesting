import json
import logging
import math
import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from collections import OrderedDict
from pathlib import Path
from datetime import date, timedelta
from typing import Any, List

import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rsi_supertrend_backtester.backtest.portfolio import PortfolioBacktester
from rsi_supertrend_backtester.core.config import load_config
from rsi_supertrend_backtester.core.indicators import add_supertrend
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

logger = logging.getLogger(__name__)

app = FastAPI(title="RSI Supertrend Backtester API")

# ── Order monitor startup ────────────────────────────────────────────────────
from rsi_supertrend_backtester.orders import monitor as order_monitor
from rsi_supertrend_backtester.orders import trade_store, dhan_client

@app.on_event("startup")
async def _on_startup():
    """Start order monitor, background feed, and pre-warm the backtest process pool."""
    global _backtest_pool
    import multiprocessing
    cpu_count = multiprocessing.cpu_count()
    pool_workers = max(4, min(cpu_count, 16))
    logger.info(f"Pre-warming backtest ProcessPoolExecutor with {pool_workers} workers...")
    if _backtest_pool is None:
        _backtest_pool = ProcessPoolExecutor(max_workers=pool_workers)
    _backtest_pool.submit(_pool_warmup)  # trigger worker init now, not on first request
    logger.info(f"Backtest pool warmed up ({pool_workers} workers ready).")

    if os.getenv("RSI_DISABLE_DHAN_BACKGROUND", "").strip().lower() in {"1", "true", "yes", "on"}:
        logger.info("Dhan background monitor disabled for this server process.")
        return
    order_monitor.ensure_monitor_running()
    asyncio.create_task(_ensure_background_feed())
    logger.info("Order monitor and Background Price Monitor started on app startup.")

import multiprocessing
multiprocessing.freeze_support()  # required for Windows PyInstaller / subprocess spawn

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = BASE_DIR / "static"

# ── Global pre-warmed process pool (shared across all requests) ───────────────
# Workers are spawned ONCE at server start, not per-request.
# This means zero spawn overhead when running a backtest.
def _pool_warmup():
    """Dummy task to trigger worker process initialization (imports numpy/pandas)."""
    import pandas  # noqa: F401
    import numpy   # noqa: F401
    return True

_pool_workers = max(4, min(multiprocessing.cpu_count(), 16))
_backtest_pool = None

_ENTRY_PREVIEW_FRAME_CACHE_MAX = 80
_ENTRY_PREVIEW_FRAME_CACHE: OrderedDict[
    tuple[Any, ...],
    tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, int]],
] = OrderedDict()

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.websockets import WebSocketDisconnect
from fastapi import WebSocket

import os
import struct
import websockets as ws_lib
from dotenv import load_dotenv

# ── DhanHQ credentials ──────────────────────────────────────────────────────
load_dotenv(BASE_DIR / ".env")
DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

# ── Shared price store: {security_id: {ltp, symbol}} ───────────────────────
_live_prices: dict = {}
_ws_clients: set  = set()     # connected browser WebSocket clients

# ── Instrument master cache: {symbol: security_id} ─────────────────────────
_symbol_to_secid: dict = {}
_instrument_df   = None

def _load_instrument_master() -> "pd.DataFrame | None":
    """Load DhanHQ instrument master CSV from the Data Collection cache."""
    import pandas as pd
    candidate_paths = [
        Path("D:/RSI_SuperTrand/Data Collection/backend/cache/instrument_master.csv"),
        BASE_DIR.parent.parent / "Data Collection" / "backend" / "cache" / "instrument_master.csv",
    ]
    for p in candidate_paths:
        if p.exists():
            try:
                df = pd.read_csv(p, low_memory=False)
                logger.info(f"Loaded instrument master: {len(df)} rows from {p}")
                return df
            except Exception as e:
                logger.warning(f"Failed to load instrument master from {p}: {e}")
    logger.warning("Instrument master CSV not found — live prices will not be available")
    return None

def resolve_security_id(symbol: str) -> str | None:
    """Return DhanHQ security_id for a NSE_EQ equity symbol, or None."""
    global _instrument_df, _symbol_to_secid
    if symbol in _symbol_to_secid:
        return _symbol_to_secid[symbol]
    if _instrument_df is None:
        _instrument_df = _load_instrument_master()
    if _instrument_df is None:
        return None
    df = _instrument_df
    sym_upper = symbol.upper().strip()
    mask = (
        ((df["SYMBOL_NAME"].str.upper().str.strip() == sym_upper) | 
         (df.get("UNDERLYING_SYMBOL", df["SYMBOL_NAME"]).str.upper().str.strip() == sym_upper)) &
        (df["EXCH_ID"].str.upper() == "NSE") &
        (df["SEGMENT"].str.upper() == "E") &
        (df["INSTRUMENT"].str.upper() == "EQUITY")
    )
    matched = df[mask]
    if len(matched) == 0:
        return None
    sec_id = str(matched.iloc[0]["SECURITY_ID"])
    _symbol_to_secid[symbol] = sec_id
    return sec_id

# ── DhanHQ WebSocket helper ─────────────────────────────────────────────────
DHAN_WSS_V2 = "wss://api-feed.dhan.co?version=2&token={token}&clientId={cid}&authType=2"
NSE_SEGMENT  = 1    # NSE_EQ constant for Dhan feed
QUOTE_MODE   = 15   # Ticker packet type (15 instead of 17 for simpler parsing)

def _parse_dhan_quote(data: bytes) -> dict | None:
    """Parse a DhanHQ binary Quote or Ticker packet → dict with ltp."""
    try:
        packet_type = struct.unpack_from('<B', data, 0)[0]
        if packet_type == 2 and len(data) >= 16:  # Ticker packet
            security_id = struct.unpack_from('<I', data, 4)[0]
            ltp = struct.unpack_from('<f', data, 8)[0]
            return {"security_id": str(security_id), "ltp": round(float(ltp), 2)}
        elif packet_type in (15, 17, 21) and len(data) >= 51:  # Quote packet
            security_id  = struct.unpack_from('<I', data, 2)[0]
            ltp          = struct.unpack_from('<f', data, 6)[0]
            return {"security_id": str(security_id), "ltp": round(float(ltp), 2)}
        return None
    except Exception:
        return None

async def _dhan_feed_task(instruments: list[tuple[str, str]]):
    """
    Background task: open DhanHQ WSS v2, subscribe to instruments, and
    broadcast price updates to all connected browser clients.

    instruments: list of (security_id, symbol)
    """
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        logger.warning("DhanHQ credentials missing — live feed not started")
        return

    url = DHAN_WSS_V2.format(token=DHAN_ACCESS_TOKEN, cid=DHAN_CLIENT_ID)
    secid_to_sym = {sid: sym for sid, sym in instruments}

    sub_payload = {
        "RequestCode": QUOTE_MODE,
        "InstrumentCount": len(instruments),
        "InstrumentList": [
            {"ExchangeSegment": "NSE_EQ", "SecurityId": sid}
            for sid, _ in instruments
        ]
    }

    logger.info(f"DhanFeed: connecting for {len(instruments)} instruments")
    while True:
        try:
            async with ws_lib.connect(url, ping_interval=None, ping_timeout=None) as ws:
                await ws.send(json.dumps(sub_payload))
                logger.info("DhanFeed: subscribed to instruments")
                async for message in ws:
                    if isinstance(message, bytes):
                        tick = _parse_dhan_quote(message)
                        if tick:
                            sid = tick["security_id"]
                            sym = secid_to_sym.get(sid, sid)
                            ltp = tick["ltp"]
                            _live_prices[sid] = {"ltp": ltp, "symbol": sym}
                            # ── SL Guard: check ENTRY_PENDING trades on every tick (event-driven, zero cost)
                            order_monitor.check_sl_breach_on_tick(sid, ltp)
                            # Broadcast to all connected browser WS clients
                            payload = json.dumps({"symbol": sym, "ltp": ltp, "security_id": sid})
                            for client in list(_ws_clients):
                                try:
                                    await client.send_text(payload)
                                except Exception:
                                    _ws_clients.discard(client)
            logger.warning("DhanFeed: connection closed, reconnecting in 5s...")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("DhanFeed: task cancelled")
            break
        except Exception as e:
            logger.error(f"DhanFeed error: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)



@app.get("/")
def read_root():
    return RedirectResponse(url="/static/index.html")

# ── Global reference to the DhanHQ feed background task ────────────────────
_feed_task: asyncio.Task | None = None
_feed_signature: tuple[tuple[str, str], ...] = ()
_portfolio_watchlist: dict[str, str] = {}


async def _collect_active_trade_instruments() -> list[tuple[str, str]]:
    """Build the unique list of instruments needed for pending/active trade monitoring."""
    trades = trade_store.load_all_trades()
    active_trades = [t for t in trades if t.get("status") in ("ENTRY_PENDING", "ACTIVE")]

    instruments: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for t in active_trades:
        sid = t.get("security_id")
        sym = t.get("company")
        if sid and str(sid) not in seen_ids:
            instruments.append((str(sid), sym))
            seen_ids.add(str(sid))
        elif sym:
            candidates, _ = await instrument_master.resolve_symbol(sym)
            if candidates:
                resolved_sid = str(candidates[0].security_id)
                if resolved_sid not in seen_ids:
                    instruments.append((resolved_sid, sym))
                    seen_ids.add(resolved_sid)
    for sid, sym in _portfolio_watchlist.items():
        if sid and str(sid) not in seen_ids:
            instruments.append((str(sid), sym or str(sid)))
            seen_ids.add(str(sid))
    return instruments


async def _refresh_background_feed(force_restart: bool = False) -> None:
    """
    Ensure the background Dhan price feed watches the exact set of active trades.
    Restart immediately when the subscription list changes so new pending orders
    get live SL protection without waiting for a stale feed to age out.
    """
    global _feed_task, _feed_signature

    if os.getenv("RSI_DISABLE_DHAN_BACKGROUND", "").strip().lower() in {"1", "true", "yes", "on"}:
        return

    instruments = await _collect_active_trade_instruments()
    signature = tuple(sorted((sid, sym or sid) for sid, sym in instruments))


    if not signature:
        if _feed_task is not None and not _feed_task.done():
            _feed_task.cancel()
        _feed_task = None
        _feed_signature = ()
        return

    should_restart = (
        force_restart
        or _feed_task is None
        or _feed_task.done()
        or signature != _feed_signature
    )
    if not should_restart:
        return

    if _feed_task is not None and not _feed_task.done():
        _feed_task.cancel()

    _feed_signature = signature
    _feed_task = asyncio.create_task(_dhan_feed_task(list(signature)))
    logger.info(f"Background Price Monitor: feed refreshed for {len(signature)} instruments")

async def _ensure_background_feed():
    """
    Background task that keeps the Dhan price feed alive for all active trades,
    regardless of whether any browser is connected.
    """
    global _feed_task
    logger.info("Background Price Monitor: starting...")
    while True:
        try:
            await _refresh_background_feed()
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Background Price Monitor error: {e}", exc_info=True)
            await asyncio.sleep(10)



@app.websocket("/ws/live-prices")
async def live_prices_ws(websocket: WebSocket):
    """
    Browser connects here to receive live LTP updates.
    The server uses the existing background feed and streams price ticks back.
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info(f"Browser WS connected — total clients: {len(_ws_clients)}")
    try:
        # Send any cached prices immediately
        for sid, data in _live_prices.items():
            await websocket.send_text(json.dumps({
                "symbol": data["symbol"],
                "ltp": data["ltp"],
                "security_id": sid
            }))

        # Keep connection alive with pings
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except Exception:
        pass
    finally:
        _ws_clients.discard(websocket)
        logger.info(f"Browser WS disconnected — remaining: {len(_ws_clients)}")


class TradeManagementTargetRequest(BaseModel):
    book_pct: float = 0.0
    trigger_pct: float = 0.0
    stoploss_pct: float | None = 0.0


class BacktestRequest(BaseModel):
    companies: str
    start_date: str = "2021-01-01"
    end_date: str = "2025-12-31"
    ltf: str = "Day"
    htf: str = "Week"
    supertrend_period: int = 21
    supertrend_multiplier: float = 1.5
    htf_supertrend_period: int = 21
    htf_supertrend_multiplier: float = 1.0
    rsi_ltf_period: int = 14
    rsi_ltf_min: float = 50.0
    rsi_ltf_max: float = 90.0
    rsi_htf_period: int = 14
    rsi_htf_min: float = 50.0
    rsi_htf_max: float = 90.0
    target_level: int = 17
    look_forward_limit: int = 1575
    entry_lookahead_bars: int = 1
    max_stoploss_pct: float = 5.0
    stoploss_mode: str = "signal_candle_low"
    max_parallel: int = 1
    target_mode: str = "fixed"        # "fixed" or "dynamic"
    atr_multiplier: float = 2.0       # used when target_mode == "dynamic"
    entry_offset_pct: float = 0.0     # e.g. 0.5 means entry = breakout_price * 1.005
    min_adx: float = 0.0
    min_candle_range: float = 0.0
    max_candle_range: float = 100.0
    candle_range_type: str = "range"
    pre_final_close_lf_min: float | None = None
    pre_final_max_high_lf_min: float | None = 3.0
    trade_management_enabled: bool = False
    trade_management_book_pct: float = 0.0
    trade_management_trigger_pct: float = 0.0
    trade_management_targets: list[TradeManagementTargetRequest] = Field(default_factory=list)


class EntryOffsetPreviewRequest(BaseModel):
    signals: list[dict[str, Any]]
    entry_offset_pct: float = 0.0
    ltf: str = "Day"
    htf: str = "Week"
    supertrend_period: int = 21
    supertrend_multiplier: float = 1.5
    htf_supertrend_period: int = 21
    htf_supertrend_multiplier: float = 1.0
    rsi_ltf_period: int = 14
    rsi_htf_period: int = 14
    look_forward_limit: int = 1575
    entry_lookahead_bars: int = 1
    max_stoploss_pct: float = 5.0
    stoploss_mode: str = "signal_candle_low"
    trade_management_enabled: bool = False
    trade_management_book_pct: float = 0.0
    trade_management_trigger_pct: float = 0.0
    trade_management_targets: list[TradeManagementTargetRequest] = Field(default_factory=list)


def _entry_preview_file_signature(path: Path) -> tuple[str, int | None, int | None]:
    if not path.exists():
        return (str(path), None, None)
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _entry_preview_frame_cache_key(config, req: EntryOffsetPreviewRequest, company: str) -> tuple[Any, ...]:
    data_dir = Path(config.data_dir)
    loader = MarketDataLoader(data_dir)
    execution_suffix = config.signal_settings.execution_timeframe_file_suffix
    paths = (
        loader.resolve_timeframe_path(company, req.ltf),
        loader.resolve_timeframe_path(company, execution_suffix),
    )
    return (
        str(data_dir),
        company,
        req.ltf,
        execution_suffix,
        req.supertrend_period,
        req.supertrend_multiplier,
        req.stoploss_mode,
        tuple(_entry_preview_file_signature(path) for path in paths),
    )


def _load_entry_preview_frames(
    loader: MarketDataLoader,
    config,
    req: EntryOffsetPreviewRequest,
    company: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, int]]:
    execution_suffix = config.signal_settings.execution_timeframe_file_suffix

    signal_df = loader._read_csv(loader.resolve_timeframe_path(company, req.ltf))
    execution_df = loader._read_csv(loader.resolve_timeframe_path(company, execution_suffix))

    # Preview replay only needs LTF trend state for trend-reversal exits.
    # RSI/HTF/MACD/CMF/ADX/EMA were already used when the base trades were generated.
    signal_df = add_supertrend(
        signal_df,
        period=req.supertrend_period,
        multiplier=req.supertrend_multiplier,
    ).reset_index(drop=True)
    if req.stoploss_mode == "daily_supertrend":
        sl_st_df = add_supertrend(
            signal_df[["datetime", "open", "high", "low", "close"]].copy(),
            period=req.supertrend_period,
            multiplier=1.5,
        )
        signal_df["stoploss_supertrend_lowerband"] = sl_st_df["final_lowerband"].to_numpy()

    execution_df = execution_df.copy()
    execution_df["datetime"] = pd.to_datetime(execution_df["datetime"]).dt.tz_localize(None)
    execution_df = execution_df.set_index("datetime")

    signal_time_index = {
        pd.Timestamp(row_time): int(idx)
        for idx, row_time in signal_df["datetime"].items()
    }
    return signal_df, execution_df, signal_time_index


@app.post("/api/backtest")
async def run_backtest_endpoint(req: BacktestRequest):
    logger.info(f"=== RECEIVED BACKTEST REQUEST ===\nPayload: {req.dict()}\n===============================")
    with open(BASE_DIR / "last_request.json", "w") as f:
        f.write(req.json())
    config_path = BASE_DIR / "config.json"
    config = load_config(str(config_path))
    
    if req.companies.strip().upper() == "ALL":
        csv_path = Path(config.data_dir) / "companies_1yr_daily_candles.csv"
        try:
            if csv_path.exists():
                df_master = pd.read_csv(csv_path, usecols=['symbol'])
                companies = df_master['symbol'].unique().tolist()
            else:
                companies = config.companies
        except Exception as e:
            logger.error(f"Failed to load ALL companies from {csv_path}: {e}")
            companies = config.companies
    else:
        companies = [c.strip().strip("'\"") for c in req.companies.split(",") if c.strip()]

    async def backtest_generator():
        loader = MarketDataLoader(config.data_dir)
        selected_entry_lookahead_bars = max(1, min(4, req.entry_lookahead_bars))
        entry_lookahead_variants = (selected_entry_lookahead_bars,)

        from rsi_supertrend_backtester.core.backtest_worker import process_single_company_worker
        # Re-use the global pre-warmed pool — no process spawn overhead
        global _backtest_pool
        if _backtest_pool is None:
            _backtest_pool = ProcessPoolExecutor(max_workers=_pool_workers)
        backtest_executor = _backtest_pool

        try:
            def build_strategy(entry_lookahead_bars: int) -> RSISupertrendStrategy:
                return RSISupertrendStrategy(StrategySettings(
                    rsi_period=req.rsi_ltf_period,
                    rsi_min=req.rsi_ltf_min,
                    rsi_max=req.rsi_ltf_max,
                    htf_rsi_period=req.rsi_htf_period,
                    htf_rsi_min=req.rsi_htf_min,
                    htf_rsi_max=req.rsi_htf_max,
                    supertrend_period=req.supertrend_period,
                    supertrend_multiplier=req.supertrend_multiplier,
                    htf_supertrend_period=req.htf_supertrend_period,
                    htf_supertrend_multiplier=req.htf_supertrend_multiplier,
                    entry_lookahead_bars=entry_lookahead_bars,
                    max_stoploss_pct=req.max_stoploss_pct / 100.0,
                    stoploss_mode=req.stoploss_mode,
                    look_forward_limit=req.look_forward_limit,
                    target_mode=req.target_mode,
                    atr_multiplier=req.atr_multiplier,
                    entry_offset_pct=req.entry_offset_pct,
                    trade_management_enabled=req.trade_management_enabled,
                    trade_management_book_pct=req.trade_management_book_pct,
                    trade_management_trigger_pct=req.trade_management_trigger_pct,
                    trade_management_targets=[
                        {
                            "book_pct": target.book_pct,
                            "trigger_pct": target.trigger_pct,
                            "stoploss_pct": target.stoploss_pct,
                        }
                        for target in req.trade_management_targets
                    ],
                ))

            strategies_by_bars = {
                bars: build_strategy(bars)
                for bars in entry_lookahead_variants
            }
            prepare_strategy = strategies_by_bars[selected_entry_lookahead_bars]

            event_queue = asyncio.Queue()
            all_signals_by_bars = {str(bars): [] for bars in entry_lookahead_variants}
            backtest_errors = []
            semaphore = asyncio.Semaphore(_pool_workers * 4)  # keep pool queue full without flooding

            def parse_date(date_str):
                try:
                    return pd.to_datetime(date_str)
                except:
                    try:
                        return pd.to_datetime(date_str, format="%d%m%Y")
                    except:
                        return pd.to_datetime(date_str, dayfirst=True)

            start_dt = parse_date(req.start_date)
            end_dt = parse_date(req.end_date)
            end_is_date_only = end_dt == end_dt.normalize()
            end_exclusive = end_dt + pd.Timedelta(days=1) if end_is_date_only else None

            # Build serializable payload template (picklable for ProcessPoolExecutor)
            settings_dict = {
                "rsi_period": req.rsi_ltf_period,
                "rsi_min": req.rsi_ltf_min,
                "rsi_max": req.rsi_ltf_max,
                "htf_rsi_period": req.rsi_htf_period,
                "htf_rsi_min": req.rsi_htf_min,
                "htf_rsi_max": req.rsi_htf_max,
                "supertrend_period": req.supertrend_period,
                "supertrend_multiplier": req.supertrend_multiplier,
                "htf_supertrend_period": req.htf_supertrend_period,
                "htf_supertrend_multiplier": req.htf_supertrend_multiplier,
                "max_stoploss_pct": req.max_stoploss_pct / 100.0,
                "stoploss_mode": req.stoploss_mode,
                "look_forward_limit": req.look_forward_limit,
                "target_mode": req.target_mode,
                "atr_multiplier": req.atr_multiplier,
                "entry_offset_pct": req.entry_offset_pct,
                "trade_management_enabled": req.trade_management_enabled,
                "trade_management_book_pct": req.trade_management_book_pct,
                "trade_management_trigger_pct": req.trade_management_trigger_pct,
                "trade_management_targets": [
                    {"book_pct": t.book_pct, "trigger_pct": t.trigger_pct, "stoploss_pct": t.stoploss_pct}
                    for t in req.trade_management_targets
                ],
            }
            base_payload = {
                "data_dir": str(config.data_dir),
                "ltf": req.ltf,
                "execution_timeframe_file_suffix": config.signal_settings.execution_timeframe_file_suffix,
                "htf": req.htf,
                "target_level": req.target_level,
                "start_dt": str(start_dt),
                "end_dt": str(end_dt),
                "end_exclusive": str(end_exclusive) if end_exclusive is not None else None,
                "entry_lookahead_variants": list(entry_lookahead_variants),
                "settings": settings_dict,
                "rsi_ltf_min": req.rsi_ltf_min,
                "rsi_ltf_max": req.rsi_ltf_max,
                "rsi_htf_min": req.rsi_htf_min,
                "rsi_htf_max": req.rsi_htf_max,
            }

            async def worker(company):
                async with semaphore:
                    await event_queue.put({"type": "started", "company": company})
                    loop = asyncio.get_running_loop()
                    payload = {**base_payload, "company": company}
                    try:
                        result = await asyncio.wait_for(
                            loop.run_in_executor(
                                backtest_executor, process_single_company_worker, payload
                            ),
                            timeout=60.0,
                        )
                    except asyncio.TimeoutError:
                        result = {
                            "company": company,
                            "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
                            "error": f"Timeout: {company} took >60s and was skipped",
                        }
                    except Exception as ex:
                        logger.error(f"Executor failed for {company}: {ex}")
                        result = {
                            "company": company,
                            "signals_by_bars": {str(bars): [] for bars in entry_lookahead_variants},
                            "error": f"Executor Error: {ex}",
                        }
                    await event_queue.put({
                        "type": "finished",
                        "company": company,
                        "signals_by_bars": result["signals_by_bars"],
                        "entry_lookahead_counts": {
                            key: len(value)
                            for key, value in result["signals_by_bars"].items()
                        },
                        "error": result.get("error"),
                    })

            # Start all tasks
            tasks = [asyncio.create_task(worker(c)) for c in companies]

            import time
            start_time = time.time()

            yield f"data: {json.dumps({'type': 'start', 'total': len(companies), 'entry_lookahead_variants': list(entry_lookahead_variants)})}\n\n"

            completed_count = 0
            while completed_count < len(companies):
                event = await event_queue.get()
                if event["type"] == "finished":
                    completed_count = completed_count + 1
                    for key in all_signals_by_bars:
                        all_signals_by_bars[key].extend(event.get("signals_by_bars", {}).get(key, []))
                    if event.get("error"):
                        backtest_errors.append({"company": event["company"], "error": event["error"]})

                # Forward the event to the frontend
                frontend_event = dict(event)
                frontend_event.pop("signals_by_bars", None)
                yield f"data: {json.dumps(frontend_event)}\n\n"

            end_time = time.time()
            duration_seconds = float(end_time - start_time)

            selected_signals = all_signals_by_bars[str(selected_entry_lookahead_bars)]

            def calculate_metrics(signals: list[dict[str, Any]]) -> dict[str, Any]:
                total_trades = len(signals)
                target_hits = [s for s in signals if s["target_hit"]]
                stoploss_hits = [s for s in signals if s["stoploss_hit"]]

                pos_exc_target = [s for s in signals if not s["target_hit"] and (s.get("expired_metrics") or 0) > 0]
                neg_exc_stoploss = [s for s in signals if not s["stoploss_hit"] and (s.get("expired_metrics") or s.get("stoploss_hit_metrics") or 0) < 0]

                sum_target_hit_pct = sum([float(s.get("target_hit_metrics") or 0) for s in target_hits])
                sum_stoploss_hit_pct = sum([abs(float(s.get("stoploss_hit_metrics") or 0)) for s in stoploss_hits])

                sum_pos_pct = sum_target_hit_pct + sum([float(s.get("expired_metrics") or 0) for s in signals if not s["target_hit"] and (s.get("expired_metrics") or 0) > 0])
                sum_neg_pct = sum_stoploss_hit_pct + sum([abs(float(s.get("expired_metrics") or s.get("stoploss_hit_metrics") or 0)) for s in signals if not s["stoploss_hit"] and (s.get("expired_metrics") or s.get("stoploss_hit_metrics") or 0) < 0])

                win_rate = float(len(target_hits) / total_trades * 100) if total_trades > 0 else 0.0
                return {
                    "total": total_trades,
                    "win_rate_pct": round(win_rate, 2),
                    "total_target_hits": len(target_hits),
                    "sum_target_hit_pct": round(sum_target_hit_pct, 2),
                    "total_stoploss_hits": len(stoploss_hits),
                    "sum_stoploss_hit_pct": round(sum_stoploss_hit_pct, 2),
                    "total_pos_exc_target": len(pos_exc_target),
                    "total_neg_exc_stoploss": len(neg_exc_stoploss),
                    "sum_pos_pct": round(sum_pos_pct, 2),
                    "sum_neg_pct": round(sum_neg_pct, 2),
                    "net_profit_pct": round(float(sum_pos_pct - sum_neg_pct), 2),
                }

            final_data = {
                "type": "complete",
                    "metrics": {
                        **calculate_metrics(selected_signals),
                        "time_taken_seconds": round(duration_seconds, 2),
                        "error_count": len(backtest_errors),
                    },
                    "signals": selected_signals,
                    "entry_lookahead_variants": all_signals_by_bars,
                    "entry_lookahead_variant_counts": {
                        key: len(value)
                        for key, value in all_signals_by_bars.items()
                    },
                    "selected_entry_lookahead_bars": selected_entry_lookahead_bars,
                    "errors": backtest_errors,
                }

            # ── Auto-save results to output/ so they survive restarts ──────────
            try:
                from datetime import datetime as _dt
                output_dir = BASE_DIR / "output"
                output_dir.mkdir(exist_ok=True)
                ts = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
                n_companies = len(companies)
                save_path = output_dir / f"backtest_{ts}_{n_companies}stocks.json"
                save_payload = {
                    "signals": selected_signals,
                    "baseSignals": selected_signals,
                    "entryLookaheadVariants": all_signals_by_bars,
                    "baseEntryLookaheadVariants": all_signals_by_bars,
                    "selectedEntryLookaheadBars": selected_entry_lookahead_bars,
                    "settings": req.model_dump() if hasattr(req, "model_dump") else req.dict(),
                    "timeTaken": round(duration_seconds, 2),
                    "metrics": final_data["metrics"],
                }
                tmp_save_path = save_path.with_suffix(save_path.suffix + ".tmp")
                with open(tmp_save_path, "w", encoding="utf-8") as f:
                    json.dump(save_payload, f, default=str)
                os.replace(tmp_save_path, save_path)
                logger.info(f"Backtest auto-saved → {save_path}")
            except Exception as _e:
                try:
                    if "tmp_save_path" in locals() and tmp_save_path.exists():
                        tmp_save_path.unlink()
                except Exception:
                    pass
                logger.warning(f"Backtest auto-save failed: {_e}")
            # ────────────────────────────────────────────────────────────────────

            yield f"data: {json.dumps(final_data, default=str)}\n\n"
        finally:
            pass

    return StreamingResponse(backtest_generator(), media_type="text/event-stream")


@app.post("/api/backtest/entry-offset-preview")
async def entry_offset_preview(req: EntryOffsetPreviewRequest):
    async def preview_generator():
        preview_started = time.perf_counter()
        config = load_config(str(BASE_DIR / "config.json"))
        company_pending_counts: dict[str, int] = {}
        for trade in req.signals:
            company = str(trade.get("company") or "").strip()
            if company:
                company_pending_counts[company] = company_pending_counts.get(company, 0) + 1

        total_companies = len(company_pending_counts)
        yield f"data: {json.dumps({'type': 'start', 'total_companies': total_companies, 'total_trades': len(req.signals)})}\n\n"

        if req.entry_offset_pct <= 0:
            final_data = {
                "type": "complete",
                "signals": req.signals,
                "input_count": len(req.signals),
                "kept_count": len(req.signals),
                "removed_count": 0,
                "errors": [],
                "cache_hits": 0,
                "cache_misses": 0,
                "duration_seconds": 0.0,
                "completed_companies": total_companies,
                "total_companies": total_companies,
            }
            yield f"data: {json.dumps(final_data)}\n\n"
            return

        loader = MarketDataLoader(config.data_dir)
        strategy = RSISupertrendStrategy(
            StrategySettings(
                rsi_period=req.rsi_ltf_period,
                htf_rsi_period=req.rsi_htf_period,
                supertrend_period=req.supertrend_period,
                supertrend_multiplier=req.supertrend_multiplier,
                htf_supertrend_period=req.htf_supertrend_period,
                htf_supertrend_multiplier=req.htf_supertrend_multiplier,
                entry_lookahead_bars=max(1, min(10, req.entry_lookahead_bars)),
                max_stoploss_pct=req.max_stoploss_pct / 100.0,
                stoploss_mode=req.stoploss_mode,
                look_forward_limit=req.look_forward_limit,
                target_mode="fixed",
                entry_offset_pct=0.0,
                trade_management_enabled=req.trade_management_enabled,
                trade_management_book_pct=req.trade_management_book_pct,
                trade_management_trigger_pct=req.trade_management_trigger_pct,
                trade_management_targets=[
                    {
                        "book_pct": target.book_pct,
                        "trigger_pct": target.trigger_pct,
                        "stoploss_pct": target.stoploss_pct,
                    }
                    for target in req.trade_management_targets
                ],
            )
        )

        frame_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, int]]] = {}
        updated_signals: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        removed_count = 0
        cache_hits = 0
        cache_misses = 0
        completed_companies = 0
        completed_trades = 0
        started_companies: set[str] = set()

        class EntryPreviewSkipped(Exception):
            pass

        def get_frames(company: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, int]]:
            nonlocal cache_hits, cache_misses
            if company not in frame_cache:
                cache_key = _entry_preview_frame_cache_key(config, req, company)
                cached = _ENTRY_PREVIEW_FRAME_CACHE.get(cache_key)
                if cached is not None:
                    cache_hits += 1
                    _ENTRY_PREVIEW_FRAME_CACHE.move_to_end(cache_key)
                    frame_cache[company] = cached
                else:
                    cache_misses += 1
                    frame_cache[company] = _load_entry_preview_frames(loader, config, req, company)
                    _ENTRY_PREVIEW_FRAME_CACHE[cache_key] = frame_cache[company]
                    _ENTRY_PREVIEW_FRAME_CACHE.move_to_end(cache_key)
                    while len(_ENTRY_PREVIEW_FRAME_CACHE) > _ENTRY_PREVIEW_FRAME_CACHE_MAX:
                        _ENTRY_PREVIEW_FRAME_CACHE.popitem(last=False)
            return frame_cache[company]

        # Parallel pre-load all unique companies in background threads
        unique_companies = list(company_pending_counts.keys())
        companies_to_load = []
        for company in unique_companies:
            cache_key = _entry_preview_frame_cache_key(config, req, company)
            cached = _ENTRY_PREVIEW_FRAME_CACHE.get(cache_key)
            if cached is not None:
                cache_hits += 1
                _ENTRY_PREVIEW_FRAME_CACHE.move_to_end(cache_key)
                frame_cache[company] = cached
            else:
                companies_to_load.append(company)

        if companies_to_load:
            from concurrent.futures import ThreadPoolExecutor
            def load_company_task(company):
                try:
                    return company, _load_entry_preview_frames(loader, config, req, company)
                except Exception as e:
                    return company, e

            with ThreadPoolExecutor(max_workers=min(64, max(1, len(companies_to_load)))) as executor:
                loop = asyncio.get_running_loop()
                tasks = [loop.run_in_executor(executor, load_company_task, c) for c in companies_to_load]
                results = await asyncio.gather(*tasks)

            for company, res in results:
                if isinstance(res, Exception):
                    errors.append({"company": company, "error": f"Failed to load frames: {res}"})
                else:
                    cache_misses += 1
                    frame_cache[company] = res
                    cache_key = _entry_preview_frame_cache_key(config, req, company)
                    _ENTRY_PREVIEW_FRAME_CACHE[cache_key] = res
                    _ENTRY_PREVIEW_FRAME_CACHE.move_to_end(cache_key)
                    while len(_ENTRY_PREVIEW_FRAME_CACHE) > _ENTRY_PREVIEW_FRAME_CACHE_MAX:
                        _ENTRY_PREVIEW_FRAME_CACHE.popitem(last=False)

        for trade in req.signals:
            company = str(trade.get("company") or "").strip()
            if not company:
                removed_count += 1
                completed_trades += 1
                errors.append({"company": "UNKNOWN", "error": "Missing company in trade payload"})
                continue

            if company not in started_companies:
                started_companies.add(company)
                yield f"data: {json.dumps({'type': 'processing', 'company': company, 'completed_companies': completed_companies, 'total_companies': total_companies, 'completed_trades': completed_trades, 'total_trades': len(req.signals)})}\n\n"

            try:
                signal_df, execution_df, signal_time_index = get_frames(company)
                signal_time_raw = trade.get("signal_date") or trade.get("signal_time")
                if not signal_time_raw:
                    raise ValueError("Missing signal_date")
                signal_time = pd.to_datetime(signal_time_raw)
                if getattr(signal_time, "tzinfo", None) is not None:
                    signal_time = signal_time.tz_localize(None)
    
                signal_idx = signal_time_index.get(pd.Timestamp(signal_time))
                if signal_idx is None:
                    raise ValueError(f"Signal candle not found: {signal_time}")
    
                original_entry = float(trade.get("original_entry") or trade.get("entry"))
                new_entry = round(original_entry * (1.0 + req.entry_offset_pct / 100.0), 2)
                target_raw = trade.get("Target", trade.get("target"))
                if target_raw is None:
                    raise ValueError("Missing target price")
                target = float(target_raw)
                original_stoploss_raw = trade.get("original_stoploss", trade.get("Stoploss", trade.get("stoploss")))
                original_stoploss = float(original_stoploss_raw) if original_stoploss_raw is not None else None
                signal_low = float(trade.get("signal_low", signal_df.iloc[signal_idx]["low"]))
    
                if target <= new_entry:
                    removed_count += 1
                    raise EntryPreviewSkipped()
    
                provisional_stoploss_basis = strategy._stoploss_basis_for_signal(signal_df, signal_idx, signal_low)
                provisional_stoploss = strategy._apply_max_stoploss_cap(new_entry, provisional_stoploss_basis)
                entry_price, entry_time, gap_up_open, pullback = strategy._find_entry(
                    signal_df,
                    signal_idx,
                    execution_df,
                    provisional_stoploss,
                    new_entry,
                )

                if entry_price is None or entry_time is None:
                    removed_count += 1
                    raise EntryPreviewSkipped()

                stoploss_basis = strategy._stoploss_basis_for_entry(
                    signal_df,
                    signal_idx,
                    entry_time,
                    signal_low,
                )
                stoploss = strategy._apply_max_stoploss_cap(entry_price, stoploss_basis)
    
                future_step = strategy.settings.entry_lookahead_bars
                if signal_idx + future_step + 1 < len(signal_df):
                    lookahead_end_time = signal_df.iloc[signal_idx + future_step + 1]["datetime"]
                else:
                    lookahead_end_time = signal_df.iloc[-1]["datetime"] + pd.Timedelta(days=1)
    
                trade_result = strategy._simulate_trade(
                    signal_df=signal_df,
                    execution_df=execution_df,
                    entry_time=entry_time,
                    entry_price=entry_price,
                    stoploss=stoploss,
                    target=target,
                    lookahead_end_time=lookahead_end_time,
                )
                entry_open_info = strategy._find_entry_open_event(
                    signal_df,
                    signal_idx,
                    execution_df,
                    stoploss,
                    entry_price,
                )
    
                updated = dict(trade)
                updated.update(
                    {
                        "entry": entry_price,
                        "entry_time": str(entry_time),
                        "exit_time": str(trade_result["exit_time"]),
                        "Target": target,
                        "Stoploss": stoploss,
                        "original_target": target,
                        "original_stoploss": original_stoploss,
                        "target_hit": trade_result["target_hit"],
                        "stoploss_hit": trade_result["stoploss_hit"],
                        "expired": trade_result["expired"],
                        "expired_metrics": trade_result["expired_metrics"],
                        "stoploss_hit_metrics": trade_result["stoploss_hit_metrics"],
                        "target_hit_metrics": trade_result["target_hit_metrics"],
                        "effective_target_pct": round(((target - entry_price) / entry_price) * 100, 3),
                        "days_held": trade_result["days_held"],
                        "exit_reason": trade_result["exit_reason"],
                        "exit_type": trade_result.get("exit_type", trade_result["exit_reason"]),
                        "exit_reason_detail": trade_result.get("exit_reason_detail"),
                        "max_high_reached": trade_result["max_high_reached"],
                        "max_high_pct": round(((trade_result["max_high_reached"] - entry_price) / entry_price) * 100, 3),
                        "min_low_reached": trade_result["min_low_reached"],
                        "sl_hit_lookahead": trade_result["sl_hit_lookahead"],
                        "max_high_lookahead": trade_result["max_high_lookahead"],
                        "max_high_lookahead_time": trade_result.get("max_high_lookahead_time"),
                        "max_high_lookahead_pct": trade_result["max_high_lookahead_pct"],
                        "close_lookahead": trade_result["close_lookahead"],
                        "close_lookahead_time": trade_result.get("close_lookahead_time"),
                        "close_lookahead_pct": trade_result["close_lookahead_pct"],
                        "gap_up_open": gap_up_open,
                        "pullback_within_lookahead": pullback,
                        "entry_open": entry_open_info.get("entry_open") if entry_open_info else None,
                        "entry_open_time": str(entry_open_info.get("entry_open_time")) if entry_open_info and entry_open_info.get("entry_open_time") is not None else None,
                        "entry_open_relation": entry_open_info.get("entry_open_relation") if entry_open_info else None,
                        "entry_open_day": entry_open_info.get("entry_open_day") if entry_open_info else None,
                        "open_compared_with_entry": strategy._open_relation_label(entry_open_info.get("entry_open_relation")) if entry_open_info else None,
                        "open_check_day": strategy._entry_day_label(entry_open_info.get("entry_open_day")) if entry_open_info else None,
                        "original_entry": original_entry,
                        "preview_entry_level": new_entry,
                        "new_entry": entry_price,
                        "new_stoploss": stoploss,
                        "new_target": target,
                        "entry_difference": round(entry_price - original_entry, 3),
                        "entry_difference_pct": round(((entry_price - original_entry) / original_entry) * 100, 3) if original_entry > 0 else 0.0,
                        "what_if_entry_offset_pct": req.entry_offset_pct,
                        "what_if_target_unchanged": True,
                        "what_if_stoploss_recalculated": True,
                        "selected_gap_up_mode": "entry_offset_preview",
                        "gap_up_handling_mode": "Entry +X% Preview",
                        "entry_source": "Entry +X% Preview",
                        "entry_rejected": False,
                        "reject_reason": None,
                        "trade_management_enabled": trade_result.get("trade_management_enabled", False),
                        "trade_management_book_pct": trade_result.get("trade_management_book_pct"),
                        "trade_management_trigger_pct": trade_result.get("trade_management_trigger_pct"),
                        "trade_management_targets": trade_result.get("trade_management_targets"),
                        "trade_management_partial_booked": trade_result.get("trade_management_partial_booked", False),
                        "trade_management_partial_exit_price": trade_result.get("trade_management_partial_exit_price"),
                        "trade_management_partial_exit_time": trade_result.get("trade_management_partial_exit_time"),
                        "trade_management_stoploss_moved_to_breakeven": trade_result.get("trade_management_stoploss_moved_to_breakeven", False),
                        "trade_management_remaining_exit_pct": trade_result.get("trade_management_remaining_exit_pct"),
                        "trade_management_remaining_exit_type": trade_result.get("trade_management_remaining_exit_type"),
                        "trade_management_remaining_exit_reason": trade_result.get("trade_management_remaining_exit_reason"),
                        "trade_management_weighted_return_pct": trade_result.get("trade_management_weighted_return_pct"),
                        "trade_management_booked_qty_pct": trade_result.get("trade_management_booked_qty_pct"),
                        "trade_management_remaining_qty_pct": trade_result.get("trade_management_remaining_qty_pct"),
                    }
                )
                updated_signals.append(updated)
            except EntryPreviewSkipped:
                pass
            except Exception as e:
                removed_count += 1
                logger.exception(f"Entry-offset preview failed for {company}")
                errors.append({"company": company, "error": str(e)})

            completed_trades += 1
            company_pending_counts[company] -= 1
            if company_pending_counts[company] == 0:
                completed_companies += 1
                yield f"data: {json.dumps({'type': 'progress', 'company': company, 'completed_companies': completed_companies, 'total_companies': total_companies, 'completed_trades': completed_trades, 'total_trades': len(req.signals), 'kept_count': len(updated_signals), 'removed_count': removed_count})}\n\n"

        final_data = {
            "type": "complete",
            "signals": updated_signals,
            "input_count": len(req.signals),
            "kept_count": len(updated_signals),
            "removed_count": removed_count,
            "errors": errors,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "duration_seconds": round(time.perf_counter() - preview_started, 2),
            "completed_companies": completed_companies,
            "total_companies": total_companies,
        }
        yield f"data: {json.dumps(final_data)}\n\n"

    return StreamingResponse(preview_generator(), media_type="text/event-stream")


# --- DATA COLLECTION PIPELINE ENABLED ---
from datetime import date, timedelta, datetime
from rsi_supertrend_backtester.data_collection.core.instrument_master import instrument_master
from rsi_supertrend_backtester.data_collection.pipeline.job_manager import job_manager
from rsi_supertrend_backtester.data_collection.pipeline.fetcher import run_job

class LiveTradingRequest(BaseModel):
    companies: str

# Flag to globally enable/disable the Data Collection pipeline
ENABLE_DATA_COLLECTION = True

@app.post("/api/live-trading/start")
async def start_live_trading(req: LiveTradingRequest, background_tasks: BackgroundTasks):
    if not ENABLE_DATA_COLLECTION:
        raise HTTPException(status_code=403, detail="Data Collection is disabled.")

    companies_str = req.companies.strip().upper()

    symbol_map: dict[str, str] = {}

    if companies_str == "ALL":
        # Load the Nifty 500 universe from config.json, then resolve via instrument master
        config_path = BASE_DIR / "config.json"
        cfg = load_config(str(config_path))
        
        csv_path = Path(cfg.data_dir) / "companies_1yr_daily_candles.csv"
        try:
            if csv_path.exists():
                df_master = pd.read_csv(csv_path, usecols=['symbol'])
                all_symbols = df_master['symbol'].unique().tolist()
            else:
                all_symbols = [s.strip().upper() for s in cfg.companies if s.strip()]
        except Exception as e:
            logger.error(f"Failed to load ALL companies from {csv_path}: {e}")
            all_symbols = [s.strip().upper() for s in cfg.companies if s.strip()]
        for s in all_symbols:
            candidates, is_exact = await instrument_master.resolve_symbol(s)
            if candidates:
                # Take best match: exact first, otherwise first candidate
                best = candidates[0] if is_exact else candidates[0]
                symbol_map[s] = best.security_id
    else:
        # Comma-separated list of symbols (Nifty 50 / 100 / 200) — resolve individually
        symbols = [s.strip().upper() for s in companies_str.split(",") if s.strip()]
        if not symbols:
            raise HTTPException(status_code=400, detail="No symbols provided.")
        for s in symbols:
            candidates, is_exact = await instrument_master.resolve_symbol(s)
            if candidates:
                symbol_map[s] = candidates[0].security_id

    if not symbol_map:
        raise HTTPException(status_code=400, detail="Could not resolve any symbols in the instrument master.")
    
    today = date.today()
    from_date = today - timedelta(days=365*5)
    
    job = job_manager.create_job(
        symbols=list(symbol_map.keys()),
        from_date=str(from_date),
        to_date=str(today),
        exchange_segment="NSE_EQ",
        instrument="EQUITY"
    )
    
    background_tasks.add_task(
        run_job,
        job.job_id,
        symbol_map,
        from_date,
        today,
        "NSE_EQ",
        "EQUITY"
    )
    
    return {"jobId": job.job_id, "status": "started"}

@app.get("/api/live-trading/status/{job_id}")
async def get_live_trading_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "status": job.status,
        "totalSymbols": len(job.symbols),
        "completedSymbols": job.completed_symbols(),
        "failedSymbols": job.failed_symbols(),
        "totalRequests": job.total_requests,
        "symbols": {
            s: {
                "status": state.status,
                "error": state.error
            } for s, state in job.symbols_state.items()
        }
    }
# -----------------------------------------

from pydantic import BaseModel
from typing import List, Any
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import json
import time
import pandas as pd
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings
import asyncio
from concurrent.futures import ThreadPoolExecutor

class ScanRequest(BaseModel):
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
        scan_symbols = set(c.strip().strip("'\"") for c in req.companies.split(",") if c.strip())
    
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
                s = pd.to_datetime(series, format='ISO8601')
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
            def _safe_float(val, precision=2):
                if pd.isna(val) or val is None:
                    return None
                try:
                    fval = float(val)
                    import math
                    if math.isinf(fval) or math.isnan(fval):
                        return None
                    return round(fval, precision)
                except (ValueError, TypeError):
                    return None

            st_ltf_val = None
            if "final_lowerband" in row and "final_upperband" in row:
                st_ltf_val = _safe_float(row["final_lowerband"] if in_uptrend_ltf else row["final_upperband"])

            in_uptrend_htf = None
            htf_trend_str = None
            if "in_uptrend_htf" in row and pd.notna(row["in_uptrend_htf"]):
                in_uptrend_htf = bool(row["in_uptrend_htf"])
                htf_trend_str = "Uptrend" if in_uptrend_htf else "Downtrend"

            rsi_ltf = _safe_float(row.get("rsi"))
            rsi_htf = _safe_float(row.get("rsi_htf"))

            cmf_val = _safe_float(row.get("cmf"), 4)
            rel_vol = _safe_float(row.get("rel_vol"), 3)
            atr_val = _safe_float(row.get("ATR"))
            adx_val = _safe_float(row.get("adx"))
            ema_20 = _safe_float(row.get("ema_20"))

            close = _safe_float(row.get("close", 0)) or 0.0
            o = _safe_float(row.get("open", 0)) or 0.0
            h = _safe_float(row.get("high", 0)) or 0.0
            lo = _safe_float(row.get("low", 0)) or 0.0

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
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=64) as executor:
        tasks = [loop.run_in_executor(executor, process_file, df_path) for df_path in day_files]
        raw_results = await asyncio.gather(*tasks)

    results = [res for res in raw_results if res is not None]
    results.sort(key=lambda x: x.get("company", ""))
    return results

# ═══════════════════════════════════════════════════════════════════════════════
# SYMBOL RESOLUTION ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

class ResolveSymbolsRequest(BaseModel):
    symbols: List[str]

@app.post("/api/resolve-symbols")
async def resolve_symbols_endpoint(req: ResolveSymbolsRequest):
    """
    Resolve a list of NSE equity symbols to their DhanHQ security_id.
    Returns: { "SYMBOL": "security_id" or null }
    """
    result = {}
    for sym in req.symbols:
        candidates, _ = await instrument_master.resolve_symbol(sym.strip().upper())
        result[sym] = candidates[0].security_id if candidates else None
    return result


# LIVE DHAN PORTFOLIO ENDPOINTS

def _dhan_list(resp: Any) -> list[dict[str, Any]]:
    if isinstance(resp, list):
        return [x for x in resp if isinstance(x, dict)]
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("holdings", "positions", "orders", "trades"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    for key in ("holdings", "positions", "orders", "trades"):
        val = resp.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    return []


def _pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_num(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _dhan_error(resp: Any) -> str | None:
    if not isinstance(resp, dict):
        return None
    status = str(resp.get("status") or resp.get("orderStatus") or "").lower()
    if status in {"failure", "failed", "error", "rejected"}:
        return str(resp.get("remarks") or resp.get("message") or resp.get("data") or resp)
    return None


def _dhan_error_detail(resp: Any) -> str:
    if not isinstance(resp, dict):
        return str(resp)

    remarks = resp.get("remarks") if isinstance(resp.get("remarks"), dict) else {}
    data = resp.get("data") if isinstance(resp.get("data"), dict) else {}

    error_code = (
        remarks.get("error_code")
        or data.get("errorCode")
        or resp.get("errorCode")
        or ""
    )
    error_message = (
        remarks.get("error_message")
        or data.get("errorMessage")
        or resp.get("message")
        or "Unknown Dhan error"
    )

    if str(error_message).strip().lower() == "invalid ip":
        return (
            f"Dhan rejected the request: Invalid IP ({error_code or 'unknown code'}). "
            "This machine/network IP is not allowed for your Dhan API access token or app."
        )

    if error_code:
        return f"Dhan rejected the request: {error_message} ({error_code})"
    return f"Dhan rejected the request: {error_message}"


async def _fetch_dhan(name: str, func):
    try:
        resp = await asyncio.to_thread(func)
        return name, resp, _dhan_error(resp)
    except Exception as e:
        logger.error(f"Dhan portfolio fetch failed for {name}: {e}", exc_info=True)
        return name, None, str(e)


def _live_ltp(security_id: str, fallback: float = 0.0) -> float:
    cached = _live_prices.get(str(security_id)) or {}
    return _num(cached.get("ltp"), fallback)


def _pnl_pct(pnl: float, investment: float) -> float:
    return round((pnl / investment) * 100, 2) if investment else 0.0


def _managed_trade_map() -> dict[str, dict[str, Any]]:
    managed: dict[str, dict[str, Any]] = {}
    for trade in trade_store.load_all_trades():
        sid = str(trade.get("security_id") or "")
        if not sid:
            continue
        status = trade.get("status")
        if status in {trade_store.TradeStatus.ACTIVE, trade_store.TradeStatus.ENTRY_FILLED, trade_store.TradeStatus.ENTRY_PENDING}:
            managed[sid] = trade
    return managed


def _managed_trade_by_oco_order() -> dict[str, dict[str, Any]]:
    managed: dict[str, dict[str, Any]] = {}
    for trade in trade_store.load_all_trades():
        status = trade.get("status")
        if status not in {trade_store.TradeStatus.ACTIVE, trade_store.TradeStatus.ENTRY_FILLED}:
            continue
        oid = str(trade.get("target_order_id") or trade.get("sl_order_id") or "").strip()
        if oid:
            managed[oid] = trade
    return managed


def _build_holding_rows(holdings: list[dict[str, Any]], managed_by_sid: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in holdings:
        sid = str(_pick(item, "securityId", "security_id", "SECURITY_ID", default="")).strip()
        symbol = str(_pick(item, "tradingSymbol", "trading_symbol", "symbol", "SYMBOL_NAME", default=sid)).strip()
        qty = _int_num(_pick(item, "totalQty", "quantity", "qty", default=0))
        available_qty = _int_num(_pick(item, "availableQty", "dpQty", "freeQty", default=qty), qty)
        avg = _num(_pick(item, "avgCostPrice", "avgPrice", "averagePrice", "costPrice", default=0))
        fallback_ltp = _num(_pick(item, "lastTradedPrice", "ltp", "lastPrice", default=0))
        ltp = _live_ltp(sid, fallback_ltp)
        investment = round(avg * qty, 2)
        current_value = round(ltp * qty, 2) if ltp else 0.0
        pnl = round(current_value - investment, 2) if current_value else 0.0
        managed = managed_by_sid.get(sid, {})
        rows.append({
            "id": f"holding:{sid}",
            "source": "HOLDING",
            "symbol": symbol or sid,
            "security_id": sid,
            "exchange_segment": "NSE_EQ",
            "product_type": "CNC",
            "quantity": qty,
            "exit_quantity": min(available_qty, qty) if available_qty else qty,
            "avg_price": avg,
            "entry_price": _num(managed.get("entry_price"), avg),
            "target_price": managed.get("target_price"),
            "stoploss_price": managed.get("stoploss_price"),
            "ltp": ltp,
            "investment": investment,
            "current_value": current_value,
            "pnl": pnl,
            "pnl_pct": _pnl_pct(pnl, investment),
            "realized_pnl": 0.0,
            "status": "HOLDING",
            "status_label": "Holding",
            "reason": "",
            "can_exit": qty > 0 and available_qty > 0,
            "can_short": bool(sid),
            "can_cancel": False,
            "trade_id": managed.get("trade_id"),
            "sort_time": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        })
    return rows


def _build_position_rows(positions: list[dict[str, Any]], managed_by_sid: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in positions:
        sid = str(_pick(item, "securityId", "security_id", "SECURITY_ID", default="")).strip()
        symbol = str(_pick(item, "tradingSymbol", "trading_symbol", "symbol", "SYMBOL_NAME", default=sid)).strip()
        net_qty = _int_num(_pick(item, "netQty", "netQuantity", "positionQty", default=0))
        realized = _num(_pick(item, "realizedProfit", "realisedProfit", "realized_pnl", default=0))
        if net_qty == 0 and realized == 0:
            continue
        is_long = net_qty >= 0
        qty_abs = abs(net_qty)
        avg = _num(_pick(item, "buyAvg" if is_long else "sellAvg", "costPrice", "avgPrice", default=0))
        fallback_ltp = _num(_pick(item, "lastTradedPrice", "ltp", "lastPrice", default=0))
        ltp = _live_ltp(sid, fallback_ltp)
        investment = round(avg * qty_abs, 2)
        current_value = round(ltp * qty_abs, 2) if ltp else 0.0
        computed_unrealized = round((ltp - avg) * net_qty, 2) if ltp and avg else 0.0
        unrealized = _num(_pick(item, "unrealizedProfit", "unrealisedProfit", "unrealized_pnl", default=computed_unrealized), computed_unrealized)
        managed = managed_by_sid.get(sid, {})
        rows.append({
            "id": f"position:{sid}:{_pick(item, 'productType', default='')}",
            "source": "POSITION",
            "symbol": symbol or sid,
            "security_id": sid,
            "exchange_segment": _pick(item, "exchangeSegment", "exchange", default="NSE_EQ"),
            "product_type": _pick(item, "productType", default="CNC"),
            "position_type": _pick(item, "positionType", default="LONG" if is_long else "SHORT"),
            "quantity": qty_abs,
            "net_quantity": net_qty,
            "exit_quantity": qty_abs,
            "avg_price": avg,
            "entry_price": _num(managed.get("entry_price"), avg),
            "target_price": managed.get("target_price"),
            "stoploss_price": managed.get("stoploss_price"),
            "ltp": ltp,
            "investment": investment,
            "current_value": current_value,
            "pnl": round(unrealized, 2),
            "pnl_pct": _pnl_pct(unrealized, investment),
            "realized_pnl": round(realized, 2),
            "status": "OPEN" if net_qty else "CLOSED",
            "status_label": "Long" if net_qty > 0 else ("Short" if net_qty < 0 else "Closed"),
            "reason": "",
            "can_exit": qty_abs > 0,
            "can_short": bool(sid and net_qty >= 0),
            "exit_transaction_type": "SELL" if net_qty > 0 else "BUY",
            "can_cancel": False,
            "trade_id": managed.get("trade_id"),
            "sort_time": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        })
    return rows


def _build_order_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending_statuses = {"PENDING", "TRANSIT", "PART_TRADED", "AMO_REQ_RECEIVED", "VALIDATION_PENDING"}
    rows = []
    for item in orders:
        order_id = str(_pick(item, "orderId", "order_id", default="")).strip()
        sid = str(_pick(item, "securityId", "security_id", default="")).strip()
        status = str(_pick(item, "orderStatus", "order_status", "status", default="UNKNOWN")).upper()
        symbol = str(_pick(item, "tradingSymbol", "trading_symbol", "symbol", default=sid or order_id)).strip()
        qty = _int_num(_pick(item, "quantity", "orderQuantity", default=0))
        traded_qty = _int_num(_pick(item, "tradedQuantity", "tradedQty", "filledQty", default=0))
        price = _num(_pick(item, "price", "orderPrice", default=0))
        trigger = _num(_pick(item, "triggerPrice", "trigger_price", default=0))
        rows.append({
            "id": f"order:{order_id}",
            "source": "ORDER",
            "symbol": symbol or sid or order_id,
            "security_id": sid,
            "order_id": order_id,
            "exchange_segment": _pick(item, "exchangeSegment", default="NSE_EQ"),
            "product_type": _pick(item, "productType", default=""),
            "transaction_type": _pick(item, "transactionType", default=""),
            "order_type": _pick(item, "orderType", default=""),
            "quantity": qty,
            "traded_quantity": traded_qty,
            "pending_quantity": max(qty - traded_qty, 0),
            "avg_price": price,
            "entry_price": price,
            "trigger_price": trigger,
            "ltp": _live_ltp(sid, 0),
            "investment": 0.0,
            "current_value": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "status": status,
            "status_label": status.replace("_", " ").title(),
            "reason": _pick(item, "omsErrorDescription", "rejectionReason", "remarks", default=""),
            "can_exit": False,
            "can_cancel": bool(order_id and status in pending_statuses),
            "can_short": False,
            "sort_time": _pick(item, "createTime", "created_at", "updateTime", "exchangeTime", default=""),
            "created_at": _pick(item, "createTime", "created_at", default=""),
            "updated_at": _pick(item, "updateTime", "exchangeTime", default=""),
        })
    return rows


def _build_forever_rows(
    forever_orders: list[dict[str, Any]],
    managed_by_sid: dict[str, dict[str, Any]],
    managed_by_oco_order: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    open_statuses = {"PENDING", "TRANSIT", "PART_TRADED", "ACTIVE"}
    rows = []
    for item in forever_orders:
        order_id = str(_pick(item, "orderId", "order_id", default="")).strip()
        sid = str(_pick(item, "securityId", "security_id", default="")).strip()
        status = str(_pick(item, "orderStatus", "order_status", "status", default="UNKNOWN")).upper()
        symbol = str(_pick(item, "tradingSymbol", "trading_symbol", "symbol", default=sid or order_id)).strip()
        qty = _int_num(_pick(item, "quantity", "orderQuantity", default=0))
        price = _num(_pick(item, "price", "orderPrice", default=0))
        trigger = _num(_pick(item, "triggerPrice", "trigger_price", default=0))
        managed = managed_by_oco_order.get(order_id) or managed_by_sid.get(sid, {})
        leg_name = str(_pick(item, "legName", default="")).upper()

        # Dhan may return historical/tripped Forever rows that are no longer visible
        # in the live Forever Orders screen. Keep open rows, and keep non-open rows
        # only when they are still tied to an active managed trade.
        if status not in open_statuses and not managed_by_oco_order.get(order_id):
            continue

        rows.append({
            "id": f"forever:{order_id}:{leg_name or 'OCO'}",
            "source": "FOREVER",
            "symbol": symbol or sid or order_id,
            "security_id": sid,
            "order_id": order_id,
            "exchange_segment": _pick(item, "exchangeSegment", default="NSE_EQ"),
            "product_type": _pick(item, "productType", default="CNC"),
            "transaction_type": _pick(item, "transactionType", default="SELL"),
            "order_type": _pick(item, "orderType", default="OCO"),
            "quantity": qty,
            "traded_quantity": 0,
            "pending_quantity": qty,
            "avg_price": price,
            "entry_price": _num(managed.get("entry_price"), price),
            "trigger_price": trigger,
            "target_price": managed.get("target_price"),
            "stoploss_price": managed.get("stoploss_price"),
            "ltp": _live_ltp(sid, 0),
            "investment": 0.0,
            "current_value": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "status": status,
            "status_label": f"{leg_name.replace('_', ' ').title() or 'Forever'} / {status.replace('_', ' ').title()}",
            "reason": "",
            "leg_name": leg_name,
            "can_exit": False,
            "can_cancel": bool(order_id and status in open_statuses),
            "can_short": False,
            "sort_time": _pick(item, "createTime", "created_at", "updateTime", "exchangeTime", default=""),
            "created_at": _pick(item, "createTime", "created_at", default=""),
            "updated_at": _pick(item, "updateTime", "exchangeTime", default=""),
            "trade_id": managed.get("trade_id"),
        })
    return rows


def _build_managed_trade_rows(
    existing_rows: list[dict[str, Any]],
    managed_by_sid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    represented_trade_ids = {
        str(row.get("trade_id") or "").strip()
        for row in existing_rows
        if str(row.get("trade_id") or "").strip()
    }
    rows: list[dict[str, Any]] = []

    for sid, trade in managed_by_sid.items():
        trade_id = str(trade.get("trade_id") or "").strip()
        if not trade_id or trade_id in represented_trade_ids:
            continue

        status = str(trade.get("status") or "").upper()
        qty = _int_num(trade.get("filled_quantity"), _int_num(trade.get("quantity"), 0))
        if status == trade_store.TradeStatus.ENTRY_PENDING:
            qty = _int_num(trade.get("quantity"), 0)
        if qty <= 0:
            qty = _int_num(trade.get("quantity"), 0)

        entry_price = _num(trade.get("entry_price"), 0)
        ltp = _live_ltp(sid, entry_price)
        investment = round(entry_price * qty, 2) if entry_price and qty else 0.0
        current_value = round(ltp * qty, 2) if ltp and qty else 0.0
        pnl = round(current_value - investment, 2) if current_value and investment else 0.0

        rows.append({
            "id": f"managed:{trade_id}",
            "source": "MANAGED",
            "symbol": trade.get("company") or sid,
            "security_id": sid,
            "trade_id": trade_id,
            "exchange_segment": "NSE_EQ",
            "product_type": "CNC",
            "quantity": qty,
            "exit_quantity": qty,
            "avg_price": entry_price,
            "entry_price": entry_price,
            "target_price": trade.get("target_price"),
            "stoploss_price": trade.get("stoploss_price"),
            "ltp": ltp,
            "investment": investment,
            "current_value": current_value,
            "pnl": pnl,
            "pnl_pct": _pnl_pct(pnl, investment),
            "realized_pnl": 0.0,
            "status": status,
            "status_label": status.replace("_", " ").title(),
            "reason": trade.get("exit_reason") or "",
            "can_exit": status in {trade_store.TradeStatus.ACTIVE, trade_store.TradeStatus.ENTRY_FILLED} and qty > 0,
            "can_short": bool(sid and status in {
                trade_store.TradeStatus.CLOSED_WIN,
                trade_store.TradeStatus.CLOSED_LOSS,
                trade_store.TradeStatus.CANCELLED,
                trade_store.TradeStatus.REJECTED,
                trade_store.TradeStatus.SKIPPED,
            }),
            "can_cancel": False,
            "exit_transaction_type": "SELL",
            "sort_time": trade.get("placed_at") or datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        })

    return rows


def _build_today_trade_rows(existing_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    represented_trade_ids = {
        str(row.get("trade_id") or "").strip()
        for row in existing_rows
        if str(row.get("trade_id") or "").strip()
    }
    today = date.today().isoformat()
    rows: list[dict[str, Any]] = []

    for trade in trade_store.load_all_trades():
        trade_id = str(trade.get("trade_id") or "").strip()
        placed_at = str(trade.get("placed_at") or "")
        if not trade_id or trade_id in represented_trade_ids or not placed_at.startswith(today):
            continue

        sid = str(trade.get("security_id") or "").strip()
        status = str(trade.get("status") or "").upper()
        qty = _int_num(trade.get("filled_quantity"), _int_num(trade.get("quantity"), 0))
        if status == trade_store.TradeStatus.ENTRY_PENDING:
            qty = _int_num(trade.get("quantity"), 0)
        if qty <= 0:
            qty = _int_num(trade.get("quantity"), 0)

        entry_price = _num(trade.get("entry_price"), 0)
        ltp = _live_ltp(sid, entry_price)
        investment = round(entry_price * qty, 2) if entry_price and qty else 0.0
        current_value = round(ltp * qty, 2) if ltp and qty else 0.0
        pnl = round(current_value - investment, 2) if current_value and investment else 0.0

        rows.append({
            "id": f"today:{trade_id}",
            "source": "TODAY",
            "symbol": trade.get("company") or sid,
            "security_id": sid,
            "trade_id": trade_id,
            "order_id": trade.get("entry_order_id"),
            "exchange_segment": "NSE_EQ",
            "product_type": "CNC",
            "quantity": qty,
            "exit_quantity": qty,
            "avg_price": entry_price,
            "entry_price": entry_price,
            "target_price": trade.get("target_price"),
            "stoploss_price": trade.get("stoploss_price"),
            "ltp": ltp,
            "investment": investment,
            "current_value": current_value,
            "pnl": pnl,
            "pnl_pct": _pnl_pct(pnl, investment),
            "realized_pnl": 0.0,
            "status": status,
            "status_label": status.replace("_", " ").title(),
            "reason": trade.get("exit_reason") or "",
            "can_exit": status in {trade_store.TradeStatus.ACTIVE, trade_store.TradeStatus.ENTRY_FILLED} and qty > 0,
            "can_short": bool(sid and status in {
                trade_store.TradeStatus.CLOSED_WIN,
                trade_store.TradeStatus.CLOSED_LOSS,
                trade_store.TradeStatus.CANCELLED,
                trade_store.TradeStatus.REJECTED,
                trade_store.TradeStatus.SKIPPED,
            }),
            "can_cancel": status == trade_store.TradeStatus.ENTRY_PENDING,
            "exit_transaction_type": "SELL",
            "sort_time": placed_at,
            "updated_at": trade.get("updated_at") or placed_at or datetime.now().isoformat(),
        })

    return rows


def _portfolio_summary(rows: list[dict[str, Any]], orders: list[dict[str, Any]], funds: Any, errors: dict[str, str]) -> dict[str, Any]:
    exposure_rows = [r for r in rows if r.get("source") in {"HOLDING", "POSITION"}]
    investment = round(sum(_num(r.get("investment")) for r in exposure_rows), 2)
    current_value = round(sum(_num(r.get("current_value")) for r in exposure_rows), 2)
    unrealized = round(sum(_num(r.get("pnl")) for r in exposure_rows), 2)
    realized = round(sum(_num(r.get("realized_pnl")) for r in exposure_rows), 2)
    overall = round(unrealized + realized, 2)
    statuses = [str(_pick(o, "orderStatus", "order_status", "status", default="")).upper() for o in orders]
    pending_statuses = {"PENDING", "TRANSIT", "PART_TRADED", "AMO_REQ_RECEIVED", "VALIDATION_PENDING"}
    cancelled_statuses = {"CANCELLED", "REJECTED", "EXPIRED"}
    funds_dict = funds if isinstance(funds, dict) else {}
    return {
        "investment": investment,
        "current_value": current_value,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "overall_pnl": overall,
        "overall_pnl_pct": _pnl_pct(overall, investment),
        "holdings": len([r for r in rows if r.get("source") == "HOLDING"]),
        "positions": len([r for r in rows if r.get("source") == "POSITION"]),
        "orders": len(orders),
        "pending_orders": len([s for s in statuses if s in pending_statuses]),
        "active_orders": len([s for s in statuses if s in pending_statuses or s == "TRADED"]),
        "cancelled_orders": len([s for s in statuses if s in cancelled_statuses]),
        "available_balance": _num(_pick(funds_dict, "availabelBalance", "availableBalance", "available_balance", default=0)),
        "errors": errors,
    }


class PortfolioExitRequest(BaseModel):
    security_id: str
    quantity: int
    symbol: str | None = None
    product_type: str = "CNC"
    exchange_segment: str = "NSE_EQ"
    transaction_type: str = "SELL"
    trade_id: str | None = None


class PortfolioShortRequest(BaseModel):
    security_id: str
    quantity: int
    symbol: str | None = None
    product_type: str = "INTRA"
    exchange_segment: str = "NSE_EQ"


@app.get("/api/portfolio/live")
async def get_live_portfolio():
    global _portfolio_watchlist

    fetched = await asyncio.gather(
        _fetch_dhan("holdings", dhan_client.get_holdings),
        _fetch_dhan("positions", dhan_client.get_positions),
        _fetch_dhan("orders", dhan_client.get_order_list),
        _fetch_dhan("forever_orders", dhan_client.get_forever_orders),
        _fetch_dhan("funds", dhan_client.get_fund_limits),
    )
    response_map = {name: resp for name, resp, _ in fetched}
    errors = {name: err for name, _, err in fetched if err}

    holdings = _dhan_list(response_map.get("holdings"))
    positions = _dhan_list(response_map.get("positions"))
    orders = _dhan_list(response_map.get("orders"))
    forever_orders = _dhan_list(response_map.get("forever_orders"))
    funds_resp = response_map.get("funds")
    funds = funds_resp.get("data", funds_resp) if isinstance(funds_resp, dict) else {}

    managed_by_sid = _managed_trade_map()
    managed_by_oco_order = _managed_trade_by_oco_order()
    rows = (
        _build_holding_rows(holdings, managed_by_sid)
        + _build_position_rows(positions, managed_by_sid)
        + _build_order_rows(orders)
        + _build_forever_rows(forever_orders, managed_by_sid, managed_by_oco_order)
    )
    rows += _build_managed_trade_rows(rows, managed_by_sid)
    rows += _build_today_trade_rows(rows)

    watchlist: dict[str, str] = {}
    for row in rows:
        sid = str(row.get("security_id") or "")
        if sid:
            watchlist[sid] = str(row.get("symbol") or sid)
    _portfolio_watchlist = watchlist
    await _refresh_background_feed(force_restart=True)

    return {
        "source": "dhan",
        "as_of": datetime.now().isoformat(),
        "market_open": dhan_client.is_market_open(),
        "summary": _portfolio_summary(rows, orders, funds, errors),
        "rows": rows,
        "holdings": holdings,
        "positions": positions,
        "orders": orders,
        "forever_orders": forever_orders,
        "funds": funds,
        "live_prices": _live_prices,
        "errors": errors,
    }


@app.post("/api/portfolio/exit")
async def exit_portfolio_position(req: PortfolioExitRequest):
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    if not req.security_id:
        raise HTTPException(status_code=400, detail="security_id is required")

    errors: list[str] = []
    if req.trade_id:
        trade = trade_store.get_trade(req.trade_id)
        if trade and trade.get("status") == trade_store.TradeStatus.ACTIVE:
            oid = trade.get("target_order_id")
            if oid:
                try:
                    cancel_resp = await asyncio.to_thread(dhan_client.cancel_forever_order, oid)
                    if _dhan_error(cancel_resp):
                        errors.append(f"Could not cancel linked OCO order: {cancel_resp}")
                except Exception as e:
                    errors.append(f"Could not cancel linked OCO order: {e}")
        elif trade and trade.get("status") == trade_store.TradeStatus.ENTRY_PENDING:
            raise HTTPException(status_code=400, detail="Pending entry is not filled yet. Cancel the pending order instead of exiting.")

    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    resp = await asyncio.to_thread(
        dhan_client.place_market_exit,
        req.security_id,
        req.quantity,
        req.product_type,
        req.exchange_segment,
        req.transaction_type,
        f"manual-exit-{req.symbol or req.security_id}",
    )
    err = _dhan_error(resp)
    if err:
        raise HTTPException(status_code=502, detail=err)

    if req.trade_id:
        order_id = dhan_client.extract_order_id(resp)
        trade_store.update_trade(req.trade_id, {
            "manual_exit_order_id": order_id,
            "exit_requested_at": datetime.now().isoformat(),
            "exit_reason": "Manual market exit requested",
        })
        _broadcast_order_event({
            "type": "trade_update",
            "trade_id": req.trade_id,
            "exit_reason": "Manual market exit requested",
            "manual_exit_order_id": order_id,
        })

    await _refresh_background_feed(force_restart=True)
    return {"submitted": True, "response": resp}


@app.post("/api/portfolio/short")
async def short_portfolio_symbol(req: PortfolioShortRequest):
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    if not req.security_id:
        raise HTTPException(status_code=400, detail="security_id is required")

    resp = await asyncio.to_thread(
        dhan_client.place_market_exit,
        req.security_id,
        req.quantity,
        req.product_type or "INTRA",
        req.exchange_segment or "NSE_EQ",
        "SELL",
        f"manual-short-{req.symbol or req.security_id}",
    )
    err = _dhan_error(resp)
    if err:
        raise HTTPException(status_code=502, detail=err)

    await _refresh_background_feed(force_restart=True)
    return {"submitted": True, "response": resp}


@app.delete("/api/portfolio/orders/{order_id}")
async def cancel_dhan_portfolio_order(order_id: str):
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")
    resp = await asyncio.to_thread(dhan_client.cancel_order, order_id)
    err = _dhan_error(resp)
    if err:
        raise HTTPException(status_code=502, detail=err)
    await _refresh_background_feed(force_restart=True)
    return {"cancelled": True, "response": resp}


# ═══════════════════════════════════════════════════════════════════════════════
# LIVE ORDER ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

# ── WebSocket broadcast store ────────────────────────────────────────────────
_order_ws_clients: set = set()

def _broadcast_order_event(event: dict) -> None:
    """Push an order/trade event to all connected browser WebSocket clients."""
    global _order_ws_clients
    import asyncio
    payload = json.dumps(event, default=str)
    dead = set()
    for client in list(_order_ws_clients):
        try:
            asyncio.create_task(client.send_text(payload))
        except Exception:
            dead.add(client)
    _order_ws_clients -= dead

# Register broadcast function with the monitor so it can push events to the UI
order_monitor.set_broadcast(_broadcast_order_event)


@app.websocket("/ws/order-updates")
async def order_updates_ws(websocket: WebSocket):
    """
    Browser connects here to receive real-time trade status updates.
    The monitor calls broadcast() which fans out to all connected clients.
    """
    await websocket.accept()
    _order_ws_clients.add(websocket)
    logger.info(f"Order-updates WS connected — clients: {len(_order_ws_clients)}")
    try:
        # Send current trade state immediately on connect
        trades = trade_store.load_all_trades()
        await websocket.send_text(json.dumps({"type": "snapshot", "trades": trades}, default=str))
        # Keep alive
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        logger.info("Order-updates WS disconnected")
    except Exception as e:
        logger.error(f"Order-updates WS error: {e}")
    finally:
        _order_ws_clients.discard(websocket)


class PlaceEntryRequest(BaseModel):
    company:        str
    security_id:    str
    quantity:       int
    entry_price:    float
    target_price:   float
    stoploss_price: float
    signal_date:    str


@app.post("/api/orders/place-entry")
async def place_entry_order(req: PlaceEntryRequest):
    """
    Place an AMO SL Limit BUY order on Dhan and persist the trade.
    Trigger Price = entry_price, Limit Price = entry_price.
    """
    if not req.security_id:
        raise HTTPException(status_code=400, detail="security_id is required")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")

    try:
        # Look up the actual tick size for this security from the instrument master
        tick_size = instrument_master.get_tick_size(req.security_id)
        logger.info(f"Tick size for {req.company} (sec={req.security_id}): ₹{tick_size}")

        resp, order_label = dhan_client.place_entry_smart(
            security_id=req.security_id,
            quantity=req.quantity,
            entry_price=req.entry_price,
            tick_size=tick_size,
        )
        order_id = dhan_client.extract_order_id(resp)
        if not order_id:
            raise HTTPException(status_code=502, detail=_dhan_error_detail(resp))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"place_entry_order failed: {e}")
        raise HTTPException(status_code=502, detail=str(e))

    trade = trade_store.create_trade(
        company=req.company,
        security_id=req.security_id,
        quantity=req.quantity,
        entry_price=req.entry_price,
        target_price=req.target_price,
        stoploss_price=req.stoploss_price,
        signal_date=req.signal_date,
        entry_order_id=order_id,
    )

    # Ensure monitor is running
    order_monitor.ensure_monitor_running()
    await _refresh_background_feed()

    # Broadcast to any connected UI clients
    _broadcast_order_event({"type": "trade_new", **trade})

    return {
        "trade_id":       trade["trade_id"],
        "entry_order_id": order_id,
        "status":         trade["status"],
        "order_type":     order_label,
        "message":        f"{order_label} placed for {req.company}",
    }


@app.get("/api/market-status")
def get_market_status():
    """Return whether NSE market is currently open."""
    open_ = dhan_client.is_market_open()
    return {
        "market_open": open_,
        "order_type":  "Regular SL-Limit" if open_ else "AMO SL-Limit",
        "label":       "Place Order (Market Open)" if open_ else "Place AMO Order",
    }


@app.get("/api/orders/trades")
async def get_trades():
    """Return all trades (active + closed)."""
    return trade_store.load_all_trades()


@app.post("/api/orders/sync")
async def sync_trades_with_dhan():
    """
    Sync local trade statuses with Dhan's live order book.
    - Fetches today's order list from Dhan
    - For any ENTRY_PENDING trade whose entry_order_id is CANCELLED/EXPIRED on Dhan → handles retry/cancel locally
    - For any ENTRY_PENDING trade whose entry_order_id is REJECTED on Dhan → marks REJECTED locally
    - For any ACTIVE trade whose target/SL order is CANCELLED/REJECTED on Dhan → marks accordingly
    Returns a summary of changes made.
    """
    try:
        dhan_resp = dhan_client.get_order_list()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Dhan orders: {e}")

    # Build a map: order_id → Dhan status
    dhan_orders: dict[str, str] = {}
    if dhan_resp.get("status") == "success":
        for order in (dhan_resp.get("data") or []):
            oid = str(order.get("orderId") or order.get("order_id") or "")
            status = str(order.get("orderStatus") or order.get("order_status") or "").upper()
            if oid:
                dhan_orders[oid] = status

    DHAN_UNFILLED_CLOSED_STATES = {"CANCELLED", "EXPIRED"}
    DHAN_REJECTED_STATES = {"REJECTED"}
    DHAN_CANCELLED_STATES = DHAN_UNFILLED_CLOSED_STATES | DHAN_REJECTED_STATES
    _DHAN_TRADED_STATES   = {"TRADED", "FILLED", "COMPLETE", "PART_TRADED", "PARTIALLY_TRADED"}

    trades = trade_store.load_all_trades()
    changes = []

    for trade in trades:
        tid = trade["trade_id"]
        local_status = trade.get("status", "")
        company = trade.get("company", "?")

        if local_status == trade_store.TradeStatus.ENTRY_PENDING:
            eid = trade.get("entry_order_id")
            if not eid:
                continue
            dhan_status = dhan_orders.get(str(eid), "")

            if dhan_status in DHAN_UNFILLED_CLOSED_STATES:
                changes.append({"trade_id": tid, "company": company, "change": f"ENTRY_PENDING -> handled unfilled {dhan_status}"})
                await order_monitor._handle_entry_expired(trade)

            elif dhan_status in DHAN_REJECTED_STATES:
                reject_reason = (
                    next(
                        (
                            (order.get("omsErrorDescription") or order.get("remarks") or order.get("errorMessage"))
                            for order in (dhan_resp.get("data") or [])
                            if str(order.get("orderId") or order.get("order_id") or "") == str(eid)
                        ),
                        None,
                    )
                    or f"Rejected on Dhan ({dhan_status})"
                )
                trade_store.update_trade(tid, {
                    "status": trade_store.TradeStatus.REJECTED,
                    "exit_reason": str(reject_reason),
                    "closed_at": datetime.now().isoformat(),
                })
                trade_store.append_note(tid, str(reject_reason))
                changes.append({"trade_id": tid, "company": company, "change": f"ENTRY_PENDING → REJECTED ({dhan_status})"})
                _broadcast_order_event({"type": "trade_update", "trade_id": tid,
                                        "status": trade_store.TradeStatus.REJECTED,
                                        "company": company,
                                        "exit_reason": str(reject_reason)})

            elif dhan_status in _DHAN_TRADED_STATES:
                # Entry filled while monitor was offline — place Target + SL now
                logger.warning(f"[{company}] Sync: entry order {eid} is TRADED on Dhan but trade is still ENTRY_PENDING. Placing Target+SL now.")
                changes.append({"trade_id": tid, "company": company, "change": "ENTRY_PENDING → ACTIVE (fill detected by sync, placing Target+SL)"})
                await order_monitor._handle_entry_filled(trade, fill_price=None, traded_qty=trade.get("quantity"), order_status=dhan_status)

            elif order_monitor._is_sl_breached(trade):
                logger.warning(f"[{company}] Sync: Entry order {eid} is still PENDING on Dhan but SL has been breached. Cancelling now.")
                order_monitor._request_entry_cancel_due_to_sl(trade, source="sync")
                changes.append({"trade_id": tid, "company": company, "change": "ENTRY_PENDING → cancel requested on Dhan (SL breached detected by sync)"})

        elif local_status == trade_store.TradeStatus.ENTRY_FILLED:
            # Entry filled but Target/SL may not have been placed (e.g. crash between fill and order placement)
            missing_target = not trade.get("target_order_id")
            missing_sl     = not trade.get("sl_order_id")
            if missing_target or missing_sl:
                logger.warning(f"[{company}] Sync: ENTRY_FILLED but missing Target={missing_target} SL={missing_sl}. Re-placing now.")
                changes.append({"trade_id": tid, "company": company, "change": "ENTRY_FILLED: re-placing missing Target/SL orders"})
                await order_monitor._handle_entry_filled(trade, fill_price=None, traded_qty=trade.get("quantity"), order_status="TRADED")

        elif local_status == trade_store.TradeStatus.ACTIVE:
            # Check if target or SL was externally cancelled
            for key, label in [("target_order_id", "Target"), ("sl_order_id", "SL")]:
                oid = trade.get(key)
                if oid and dhan_orders.get(str(oid)) in DHAN_CANCELLED_STATES:
                    trade_store.append_note(tid, f"{label} order {oid} externally cancelled on Dhan")
                    changes.append({"trade_id": tid, "company": company, "change": f"{label} order cancelled on Dhan"})

    return {
        "synced": True,
        "dhan_orders_checked": len(dhan_orders),
        "local_trades_checked": len(trades),
        "changes": changes,
    }


@app.delete("/api/orders/trades/{trade_id}")
async def cancel_trade(trade_id: str):
    """
    Cancel a trade:
    - ENTRY_PENDING: cancel the AMO entry order on Dhan
    - ACTIVE: cancel both Target and SL orders on Dhan
    Then mark trade as CANCELLED.
    """
    trade = trade_store.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    status = trade.get("status", "")
    errors = []

    if status == trade_store.TradeStatus.ENTRY_PENDING:
        try:
            if trade.get("entry_order_id"):
                resp = dhan_client.cancel_order(trade["entry_order_id"])
                if resp.get("status") == "failure":
                    errors.append(f"Entry API rejected cancel: {resp}")
        except Exception as e:
            errors.append(f"Entry cancel exception: {e}")

    elif status == trade_store.TradeStatus.ACTIVE:
        # For ACTIVE trades, target_order_id stores the Forever OCO order ID.
        oid = trade.get("target_order_id")
        if oid:
            try:
                resp = dhan_client.cancel_forever_order(oid)
                if resp.get("status") == "failure":
                    errors.append(f"Forever API rejected cancel: {resp}")
            except Exception as e:
                errors.append(f"Forever OCO cancel exception: {e}")

    if errors:
        raise HTTPException(status_code=400, detail=f"Failed to cancel order on Dhan: {errors}")

    trade_store.update_trade(trade_id, {
        "status":      trade_store.TradeStatus.CANCELLED,
        "closed_at":   datetime.now().isoformat(),
        "exit_reason": "Manually cancelled via UI",
    })
    _broadcast_order_event({"type": "trade_update", "trade_id": trade_id, "status": trade_store.TradeStatus.CANCELLED})

    return {"trade_id": trade_id, "cancelled": True, "errors": errors}
