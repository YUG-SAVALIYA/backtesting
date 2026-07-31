from __future__ import annotations

import pandas as pd

from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import (
    RSISupertrendStrategy,
    StrategySettings,
)


def _strategy(**overrides) -> RSISupertrendStrategy:
    settings = {
        "look_forward_limit": 10,
        "trade_management_enabled": True,
        "trade_management_book_pct": 50.0,
        "trade_management_trigger_pct": 5.0,
    }
    settings.update(overrides)
    return RSISupertrendStrategy(
        StrategySettings(**settings)
    )


def _signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2024-01-01 09:15:00"),
                "close": 100.0,
                "in_uptrend": True,
                "final_lowerband": 95.0,
            }
        ]
    )


def _execution_frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {"datetime": dt, "open": open_price, "high": high, "low": low, "close": close}
            for dt, open_price, high, low, close in rows
        ]
    )
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.set_index("datetime")


def _simulate(rows: list[tuple[str, float, float, float, float]], **strategy_overrides) -> dict:
    return _strategy(**strategy_overrides)._simulate_trade(
        signal_df=_signal_frame(),
        execution_df=_execution_frame(rows),
        entry_time=pd.Timestamp("2024-01-01 09:15:00"),
        entry_price=100.0,
        stoploss=95.0,
        target=120.0,
        lookahead_end_time=pd.Timestamp("2024-01-02 09:15:00"),
    )


def test_stoploss_before_partial_book_is_plain_stoploss() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 102.0, 99.0, 101.0),
            ("2024-01-01 09:20:00", 101.0, 103.0, 94.9, 95.0),
        ]
    )

    assert result["exit_type"] == "Stoploss Hit"
    assert result["exit_reason"] == "Stoploss Hit"
    assert result["stoploss_hit"] is True
    assert result["trade_management_partial_booked"] is False
    assert result["trade_management_weighted_return_pct"] is None


def test_trade_management_breakeven_requires_partial_book() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.0, 99.0, 103.0),
            ("2024-01-01 09:20:00", 103.0, 106.0, 101.0, 105.0),
            ("2024-01-01 09:25:00", 105.0, 106.0, 99.5, 100.0),
        ]
    )

    assert result["exit_type"] == "Trade Mgmt Breakeven"
    assert result["exit_reason"] == "Trade Mgmt Breakeven"
    assert result["trade_management_partial_booked"] is True
    assert result["trade_management_stoploss_moved_to_breakeven"] is True
    assert result["trade_management_remaining_exit_pct"] == 0.0
    assert result["trade_management_remaining_exit_type"] == "Stoploss Hit"
    assert result["trade_management_weighted_return_pct"] == 2.5


def test_target_after_partial_book_uses_weighted_return_and_remaining_exit_type() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 106.0, 99.0, 105.0),
            ("2024-01-01 09:20:00", 105.0, 120.0, 101.0, 120.0),
        ]
    )

    assert result["exit_type"] == "Target Hit"
    assert result["target_hit"] is True
    assert result["trade_management_partial_booked"] is True
    assert result["trade_management_remaining_exit_type"] == "Target Hit"
    assert result["target_hit_metrics"] == 12.5
    assert result["trade_management_weighted_return_pct"] == 12.5


def test_time_limit_after_partial_book_uses_non_negative_remaining_return() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 106.0, 99.0, 105.0),
            ("2024-01-01 09:20:00", 105.0, 109.0, 101.0, 108.0),
        ]
    )

    assert result["exit_type"] == "Time Limit"
    assert result["expired"] is True
    assert result["trade_management_partial_booked"] is True
    assert result["trade_management_remaining_exit_type"] == "Time Limit"
    assert result["trade_management_remaining_exit_pct"] == 8.0
    assert result["trade_management_weighted_return_pct"] == 6.5


def test_multiple_trade_management_targets_can_fully_book_before_target() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 110.5, 102.0, 110.0),
            ("2024-01-01 09:25:00", 110.0, 115.5, 108.0, 115.0),
        ],
        trade_management_targets=[
            {"book_pct": 40.0, "trigger_pct": 4.0},
            {"book_pct": 30.0, "trigger_pct": 10.0},
            {"book_pct": 30.0, "trigger_pct": 15.0},
        ],
    )

    assert result["exit_type"] == "Trade Mgmt Booked"
    assert result["expired"] is True
    assert result["trade_management_partial_booked"] is True
    assert result["trade_management_booked_qty_pct"] == 100.0
    assert result["trade_management_remaining_qty_pct"] == 0.0
    assert result["trade_management_weighted_return_pct"] == 9.1
    assert [leg["hit"] for leg in result["trade_management_targets"]] == [True, True, True]


def test_multiple_trade_management_targets_leave_remaining_for_final_target() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 110.5, 102.0, 110.0),
            ("2024-01-01 09:25:00", 110.0, 120.0, 108.0, 120.0),
        ],
        trade_management_targets=[
            {"book_pct": 40.0, "trigger_pct": 4.0},
            {"book_pct": 30.0, "trigger_pct": 10.0},
        ],
    )

    assert result["exit_type"] == "Target Hit"
    assert result["target_hit"] is True
    assert result["trade_management_booked_qty_pct"] == 70.0
    assert result["trade_management_remaining_qty_pct"] == 30.0
    assert result["trade_management_remaining_exit_pct"] == 20.0
    assert result["trade_management_weighted_return_pct"] == 10.6


def test_stage_stoploss_updates_remaining_quantity_exit() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 105.0, 101.9, 102.0),
        ],
        trade_management_targets=[
            {"book_pct": 30.0, "trigger_pct": 4.0, "stoploss_pct": 2.0},
        ],
    )

    assert result["exit_type"] == "Trade Mgmt Stoploss"
    assert result["expired"] is True
    assert result["trade_management_remaining_exit_type"] == "Stoploss Hit"
    assert result["trade_management_remaining_exit_pct"] == 2.0
    assert result["trade_management_weighted_return_pct"] == 2.6
    assert result["trade_management_targets"][0]["stoploss_pct"] == 2.0
    assert result["trade_management_targets"][0]["stoploss_price"] == 102.0


def test_later_stage_stoploss_tightens_remaining_quantity_exit() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 110.5, 103.0, 110.0),
            ("2024-01-01 09:25:00", 110.0, 111.0, 105.9, 106.0),
        ],
        trade_management_targets=[
            {"book_pct": 30.0, "trigger_pct": 4.0, "stoploss_pct": 1.0},
            {"book_pct": 30.0, "trigger_pct": 10.0, "stoploss_pct": 6.0},
        ],
    )

    assert result["exit_type"] == "Trade Mgmt Stoploss"
    assert result["trade_management_booked_qty_pct"] == 60.0
    assert result["trade_management_remaining_qty_pct"] == 40.0
    assert result["trade_management_remaining_exit_pct"] == 6.0
    assert result["trade_management_weighted_return_pct"] == 6.6
    assert [leg["stoploss_pct"] for leg in result["trade_management_targets"]] == [1.0, 6.0]
    assert [leg["stoploss_price"] for leg in result["trade_management_targets"]] == [101.0, 106.0]


def test_stage_stoploss_cannot_exceed_stage_trigger() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 105.0, 103.9, 104.0),
        ],
        trade_management_targets=[
            {"book_pct": 30.0, "trigger_pct": 4.0, "stoploss_pct": 8.0},
        ],
    )

    assert result["exit_type"] == "Trade Mgmt Stoploss"
    assert result["trade_management_remaining_exit_pct"] == 4.0
    assert result["trade_management_targets"][0]["stoploss_pct"] == 4.0
    assert result["trade_management_targets"][0]["stoploss_price"] == 104.0


def test_zero_quantity_stage_moves_stoploss_without_booking() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 105.0, 101.9, 102.0),
        ],
        trade_management_targets=[
            {"book_pct": 0.0, "trigger_pct": 4.0, "stoploss_pct": 2.0},
        ],
    )

    assert result["exit_type"] == "Trade Mgmt Stoploss"
    assert result["trade_management_partial_booked"] is False
    assert result["trade_management_booked_qty_pct"] == 0.0
    assert result["trade_management_remaining_qty_pct"] == 100.0
    assert result["trade_management_remaining_exit_pct"] == 2.0
    assert result["trade_management_weighted_return_pct"] == 2.0
    assert result["expired_metrics"] == 2.0
    assert result["trade_management_targets"][0]["hit"] is True
    assert result["trade_management_targets"][0]["book_pct"] == 0.0


def test_zero_quantity_stage_keeps_full_quantity_for_final_target() -> None:
    result = _simulate(
        [
            ("2024-01-01 09:15:00", 100.0, 104.5, 99.0, 104.0),
            ("2024-01-01 09:20:00", 104.0, 120.0, 103.0, 120.0),
        ],
        trade_management_targets=[
            {"book_pct": 0.0, "trigger_pct": 4.0, "stoploss_pct": 2.0},
        ],
    )

    assert result["exit_type"] == "Target Hit"
    assert result["target_hit"] is True
    assert result["target_hit_metrics"] == 20.0
    assert result["trade_management_partial_booked"] is False
    assert result["trade_management_booked_qty_pct"] == 0.0
    assert result["trade_management_remaining_qty_pct"] == 100.0
