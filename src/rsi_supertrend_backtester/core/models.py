from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TradeSignal:
    company: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry: float
    target: float
    stoploss: float
    target_hit: bool
    stoploss_hit: bool
    expired: bool
    expired_metrics: float | None
    stoploss_hit_metrics: float | None
    target_hit_metrics: float | None
    target_level: int
    effective_target_pct: float
    days_held: int | None
    rsi: float | None
    rsi_htf: float | None
    in_uptrend_htf: bool | None = None
    supertrend_trend: str | None = None
    supertrend_ltf: float | None = None
    supertrend_htf: float | None = None
    atr: float | None = None
    rel_vol: float | None = None
    cmf: float | None = None
    adx: float | None = None
    ema_20: float | None = None
    price_vs_ema20: str | None = None
    exit_reason: str | None = None
    exit_type: str | None = None
    exit_reason_detail: str | None = None
    exit_price: float | None = None
    # Signal Candle OHLCV
    signal_open: float | None = None
    signal_high: float | None = None
    signal_low: float | None = None
    signal_close: float | None = None
    signal_volume: float | None = None
    # Post-entry performance
    max_high_reached: float | None = None
    max_high_pct: float | None = None
    min_low_reached: float | None = None      # minimum low seen after entry (for gap-up SL re-evaluation)
    # Lookahead performance
    sl_hit_lookahead: bool | None = None
    max_high_lookahead: float | None = None
    max_high_lookahead_time: str | None = None
    max_high_lookahead_pct: float | None = None
    close_lookahead: float | None = None
    close_lookahead_time: str | None = None
    close_lookahead_pct: float | None = None
    close_lf_replay: dict[str, Any] | None = None
    stoploss_mode: str | None = None
    stoploss_source: str | None = None
    lf_candle_low: float | None = None
    daily_supertrend_stoploss: float | None = None
    # Gap-Up metadata (always stored; used for client-side gap-up mode comparison)
    gap_up_open: float | None = None          # actual open price if gap-up occurred, else None
    pullback_within_lookahead: bool = False   # True if price pulled back to entry_level after gap-up
    entry_open: float | None = None           # first relevant day-1/day-2 open before entry decision
    entry_open_time: str | None = None
    entry_open_relation: str | None = None    # higher, lower, or equal versus original entry
    entry_open_day: int | None = None
    entry_difference: float | None = None     # selected/new entry minus original entry
    entry_difference_pct: float | None = None
    original_entry: float | None = None
    original_target: float | None = None
    original_stoploss: float | None = None
    new_entry: float | None = None
    new_stoploss: float | None = None
    new_target: float | None = None
    selected_gap_up_mode: str | None = None
    gap_up_handling_mode: str | None = None
    entry_source: str | None = None
    open_compared_with_entry: str | None = None
    open_check_day: str | None = None
    trade_management_enabled: bool = False
    trade_management_book_pct: float | None = None
    trade_management_trigger_pct: float | None = None
    trade_management_targets: list[dict[str, Any]] | None = None
    trade_management_partial_booked: bool = False
    trade_management_partial_exit_price: float | None = None
    trade_management_partial_exit_time: str | None = None
    trade_management_stoploss_moved_to_breakeven: bool = False
    trade_management_remaining_exit_pct: float | None = None
    trade_management_remaining_exit_type: str | None = None
    trade_management_remaining_exit_reason: str | None = None
    trade_management_weighted_return_pct: float | None = None
    trade_management_booked_qty_pct: float | None = None
    trade_management_remaining_qty_pct: float | None = None
    entry_rejected: bool = False
    reject_reason: str | None = None
    gap_up_modes: dict[str, dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["Target"] = payload.pop("target")
        payload["Stoploss"] = payload.pop("stoploss")
        payload["rsi_HTF"] = payload.pop("rsi_htf")
        payload["trend"] = payload.pop("supertrend_trend")
        payload["supertrend_ltf"] = payload.pop("supertrend_ltf")
        payload["supertrend_htf"] = payload.pop("supertrend_htf")
        payload["signal_date"] = payload.pop("signal_time")
        payload["effective_target_pct"] = payload.get("effective_target_pct", payload.get("target_level", 0))
        payload["exit_reason"] = payload.pop("exit_reason")
        payload["original_entry"] = payload.get("original_entry", payload.get("entry"))
        payload["original_target"] = payload.get("original_target", payload.get("Target"))
        payload["original_stoploss"] = payload.get("original_stoploss", payload.get("Stoploss"))
        payload["new_entry"] = payload.get("new_entry", payload.get("entry"))
        payload["new_stoploss"] = payload.get("new_stoploss", payload.get("Stoploss"))
        payload["new_target"] = payload.get("new_target", payload.get("Target"))
        return payload
