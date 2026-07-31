from __future__ import annotations

import pandas as pd


def to_naive_datetime(series_or_value):
    return pd.to_datetime(series_or_value).tz_localize(None)


def get_last_candle_time(current_time, df: pd.DataFrame) -> pd.Timestamp | None:
    current_time = pd.to_datetime(current_time).tz_localize(None)
    past_candles = df[df["datetime"] <= current_time]["datetime"]
    if past_candles.empty:
        return None
    return past_candles.iloc[-1]
