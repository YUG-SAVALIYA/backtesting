from __future__ import annotations

import pandas as pd

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import (
    GAP_UP_MODE_EXISTING,
    GAP_UP_MODE_GAP_ENTRY,
    GAP_UP_MODE_GAP_UPDATE,
    GAP_UP_MODE_PULLBACK,
    RSISupertrendStrategy,
    StrategySettings,
)


def _make_signal_row(
    dt: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    *,
    in_uptrend: bool = True,
    rsi: float = 72.0,
) -> dict:
    return {
        "datetime": dt,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": 1000,
        "in_uptrend": in_uptrend,
        "final_lowerband": 90.0,
        "final_upperband": 110.0,
        "rsi": rsi,
        "rsi_htf": rsi,
        "cmf": 0.1,
        "rel_vol": 1.2,
        "adx": 25.0,
        "ATR": 10.0,
        "ema_20": 90.0,
        "candle_range": 5.0,
    }


def _signal_frame(day1: dict, day2: dict, day3: dict | None = None) -> pd.DataFrame:
    rows = [
        _make_signal_row("2024-01-01 00:00:00", 98.0, 100.0, 95.0, 99.0),
        day1,
        day2,
        day3 or _make_signal_row("2024-01-04 09:15:00", 118.0, 119.0, 117.0, 118.0, in_uptrend=False, rsi=50.0),
    ]
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def _execution_frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {"datetime": dt, "open": open_price, "high": high_price, "low": low_price, "close": close_price}
            for dt, open_price, high_price, low_price, close_price in rows
        ]
    )
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.set_index("datetime")


def _run_backtest(signal_df: pd.DataFrame, execution_df: pd.DataFrame) -> dict:
    strategy = RSISupertrendStrategy(
        StrategySettings(
            entry_lookahead_bars=2,
            look_forward_limit=10,
            max_stoploss_pct=0.05,
            target_mode="fixed",
        )
    )
    signals = strategy.generate_signals("TEST", signal_df, execution_df, target_level=20)
    assert len(signals) == 1
    return signals[0].to_dict()


def test_day1_lower_open_enters_at_original_entry() -> None:
    signal_df = _signal_frame(
        _make_signal_row("2024-01-02 09:15:00", 98.0, 100.0, 96.0, 100.0),
        _make_signal_row("2024-01-03 09:15:00", 101.0, 106.0, 99.0, 104.0),
    )
    execution_df = _execution_frame(
        [
            ("2024-01-02 09:15:00", 98.0, 99.0, 96.0, 97.0),
            ("2024-01-02 09:20:00", 97.0, 100.0, 97.0, 100.0),
            ("2024-01-03 09:15:00", 101.0, 106.0, 99.0, 104.0),
            ("2024-01-04 09:15:00", 104.0, 104.0, 103.0, 103.0),
        ]
    )

    payload = _run_backtest(signal_df, execution_df)
    modes = payload["gap_up_modes"]

    assert payload["entry"] == 100.0
    assert payload["entry_time"] == "2024-01-02 09:20:00"
    assert payload["entry_open_relation"] == "lower"
    assert payload["entry_open_day"] == 1
    assert payload["original_entry"] == 100.0
    assert modes[GAP_UP_MODE_EXISTING]["entry_source"] == "Day-1 Entry Reached"
    assert modes[GAP_UP_MODE_PULLBACK]["entry"] == 100.0
    assert modes[GAP_UP_MODE_GAP_ENTRY]["entry"] == 100.0
    assert modes[GAP_UP_MODE_GAP_UPDATE]["entry"] == 100.0


def test_day2_lower_open_is_used_for_entry_context() -> None:
    signal_df = _signal_frame(
        _make_signal_row("2024-01-02 09:15:00", 98.0, 99.0, 96.0, 98.0),
        _make_signal_row("2024-01-03 09:15:00", 99.0, 102.0, 98.0, 101.0),
    )
    execution_df = _execution_frame(
        [
            ("2024-01-02 09:15:00", 98.0, 99.0, 96.0, 97.0),
            ("2024-01-02 09:20:00", 97.0, 99.4, 96.5, 98.5),
            ("2024-01-03 09:15:00", 99.0, 100.5, 98.0, 100.0),
            ("2024-01-04 09:15:00", 101.0, 101.0, 100.0, 100.5),
        ]
    )

    payload = _run_backtest(signal_df, execution_df)
    modes = payload["gap_up_modes"]

    assert payload["entry"] == 100.0
    assert payload["entry_open_relation"] == "lower"
    assert payload["entry_open_day"] == 2
    assert payload["open_check_day"] == "Day-2"
    assert modes[GAP_UP_MODE_EXISTING]["entry_source"] == "Day-2 Entry Reached"
    assert modes[GAP_UP_MODE_GAP_ENTRY]["entry_source"] == "Day-2 Entry Reached"
    assert modes[GAP_UP_MODE_GAP_ENTRY]["entry_difference"] == 0.0


def test_day2_gap_up_builds_all_mode_variants_and_preserves_existing_result() -> None:
    signal_df = _signal_frame(
        _make_signal_row("2024-01-02 09:15:00", 98.0, 99.0, 96.0, 98.5),
        _make_signal_row("2024-01-03 09:15:00", 110.0, 125.0, 99.0, 124.0),
        _make_signal_row("2024-01-04 09:15:00", 124.0, 126.0, 118.0, 120.0),
    )
    execution_df = _execution_frame(
        [
            ("2024-01-02 09:15:00", 98.0, 99.0, 96.0, 97.0),
            ("2024-01-02 09:20:00", 97.0, 99.4, 96.5, 98.5),
            ("2024-01-03 09:15:00", 110.0, 115.0, 105.0, 112.0),
            ("2024-01-03 09:20:00", 112.0, 113.0, 99.0, 101.0),
            ("2024-01-03 09:25:00", 101.0, 125.0, 100.0, 124.0),
            ("2024-01-04 09:15:00", 124.0, 126.0, 118.0, 120.0),
        ]
    )

    payload = _run_backtest(signal_df, execution_df)
    modes = payload["gap_up_modes"]
    existing = modes[GAP_UP_MODE_EXISTING]
    pullback = modes[GAP_UP_MODE_PULLBACK]
    gap_entry = modes[GAP_UP_MODE_GAP_ENTRY]
    updated = modes[GAP_UP_MODE_GAP_UPDATE]

    assert payload["selected_gap_up_mode"] == GAP_UP_MODE_EXISTING
    assert payload["entry"] == existing["entry"] == 100.0
    assert payload["Target"] == existing["Target"] == 120.0
    assert payload["Stoploss"] == existing["Stoploss"] == 95.0
    assert payload["entry_open_relation"] == "higher"
    assert payload["entry_open_day"] == 2
    assert existing["entry_source"] == "Existing Entry"
    assert existing["entry_difference"] == 0.0

    assert pullback["valid"] is True
    assert pullback["entry"] == 100.0
    assert pullback["entry_time"] == "2024-01-03 09:20:00"
    assert pullback["entry_source"] == "Pull Back Entry"

    assert gap_entry["valid"] is True
    assert gap_entry["entry"] == 110.0
    assert gap_entry["new_entry"] == 110.0
    assert gap_entry["Stoploss"] == 104.5
    assert gap_entry["Target"] == 120.0
    assert gap_entry["entry_difference"] == 10.0
    assert gap_entry["entry_source"] == "Gap-Up Entry"
    assert gap_entry["stoploss_hit"] is True

    assert updated["valid"] is True
    assert updated["entry"] == 110.0
    assert updated["new_stoploss"] == 104.5
    assert updated["new_target"] == 132.0
    assert updated["Target"] == 132.0
    assert updated["Stoploss"] == 104.5
    assert updated["stoploss_hit"] is True


def test_day1_gap_up_uses_day1_open_for_gap_context() -> None:
    signal_df = _signal_frame(
        _make_signal_row("2024-01-02 09:15:00", 110.0, 125.0, 99.0, 124.0),
        _make_signal_row("2024-01-03 09:15:00", 124.0, 126.0, 118.0, 120.0),
    )
    execution_df = _execution_frame(
        [
            ("2024-01-02 09:15:00", 110.0, 115.0, 105.0, 112.0),
            ("2024-01-02 09:20:00", 112.0, 113.0, 99.0, 101.0),
            ("2024-01-02 09:25:00", 101.0, 125.0, 100.0, 124.0),
            ("2024-01-03 09:15:00", 124.0, 126.0, 118.0, 120.0),
            ("2024-01-04 09:15:00", 120.0, 121.0, 119.0, 120.0),
        ]
    )

    payload = _run_backtest(signal_df, execution_df)
    modes = payload["gap_up_modes"]

    assert payload["entry_open_day"] == 1
    assert payload["entry_open_relation"] == "higher"
    assert payload["open_check_day"] == "Day-1"
    assert payload["entry_open"] == 110.0
    assert modes[GAP_UP_MODE_GAP_ENTRY]["entry"] == 110.0
    assert modes[GAP_UP_MODE_GAP_ENTRY]["open_check_day"] == "Day-1"


def test_pullback_mode_rejects_gap_up_when_pullback_never_happens() -> None:
    signal_df = _signal_frame(
        _make_signal_row("2024-01-02 09:15:00", 110.0, 116.0, 105.0, 114.0),
        _make_signal_row("2024-01-03 09:15:00", 114.0, 118.0, 106.0, 116.0),
    )
    execution_df = _execution_frame(
        [
            ("2024-01-02 09:15:00", 110.0, 115.0, 105.0, 112.0),
            ("2024-01-02 09:20:00", 112.0, 116.0, 106.0, 114.0),
            ("2024-01-03 09:15:00", 114.0, 118.0, 106.0, 116.0),
            ("2024-01-04 09:15:00", 116.0, 117.0, 115.0, 116.0),
        ]
    )

    payload = _run_backtest(signal_df, execution_df)
    pullback = payload["gap_up_modes"][GAP_UP_MODE_PULLBACK]
    gap_entry = payload["gap_up_modes"][GAP_UP_MODE_GAP_ENTRY]

    assert pullback["valid"] is False
    assert pullback["entry_rejected"] is True
    assert pullback["entry_source"] == "Rejected: Pull Back Not Reached"
    assert pullback["reject_reason"] == "Pull Back Not Reached"
    assert gap_entry["valid"] is True
    assert payload["gap_up_modes"][GAP_UP_MODE_EXISTING]["entry"] == payload["entry"]
