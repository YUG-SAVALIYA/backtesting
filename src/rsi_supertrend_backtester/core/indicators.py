from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def add_rsi(df: pd.DataFrame, period: int, column_name: str) -> pd.DataFrame:
    df = df.copy()
    df[column_name] = talib.RSI(df["close"].astype(float), timeperiod=period)
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    macd, signal, hist = talib.MACD(
        df["close"].astype(float),
        fastperiod=12,
        slowperiod=26,
        signalperiod=9,
    )
    df["MACD"] = macd
    df["Signal"] = signal
    df["Histogram"] = hist
    return df


def tr(df: pd.DataFrame) -> pd.Series:
    df = df.copy()
    df['previous_close'] = df['close'].shift(1)
    df['high_low'] = df['high'] - df['low']
    df['high_pc'] = abs(df['high'] - df['previous_close'])
    df['low_pc'] = abs(df['low'] - df['previous_close'])
    tr_series = df[['high_low', 'high_pc', 'low_pc']].max(axis=1)
    return tr_series


def rma(series: pd.Series, period: int) -> pd.Series:
    """Relative Moving Average (Wilder's Smoothing)"""
    rma_values = series.copy()
    rma_values.iloc[period-1] = series.iloc[:period].mean()  # first value = SMA
    for i in range(period, len(series)):
        rma_values.iloc[i] = (rma_values.iloc[i-1] * (period - 1) + series.iloc[i]) / period
    return rma_values


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    tr_series = tr(df)
    df["ATR"] = rma(tr_series, period)
    return df


def add_supertrend(df: pd.DataFrame, period: int = 21, multiplier: float = 1.0) -> pd.DataFrame:
    df = df.copy()
    hl2 = (df['high'] + df['low']) / 2
    df = add_atr(df, period)
    df['final_upperband'] = hl2 + (multiplier * df['ATR'])
    df['final_lowerband'] = hl2 - (multiplier * df['ATR'])
    df['in_uptrend'] = True

    for current in range(1, len(df.index)):
        previous = current - 1

        if df['close'].iloc[current] > df['final_upperband'].iloc[previous]:
            df.loc[df.index[current], 'in_uptrend'] = True
        elif df['close'].iloc[current] < df['final_lowerband'].iloc[previous]:
            df.loc[df.index[current], 'in_uptrend'] = False
        else:
            df.loc[df.index[current], 'in_uptrend'] = df['in_uptrend'].iloc[previous]

            if df['in_uptrend'].iloc[current] and df['final_lowerband'].iloc[current] < df['final_lowerband'].iloc[previous]:
                df.loc[df.index[current], 'final_lowerband'] = df['final_lowerband'].iloc[previous]

            if not df['in_uptrend'].iloc[current] and df['final_upperband'].iloc[current] > df['final_upperband'].iloc[previous]:
                df.loc[df.index[current], 'final_upperband'] = df['final_upperband'].iloc[previous]

    return df


def add_rel_vol(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    sma_vol = vol.rolling(window=period).mean()
    df["rel_vol"] = vol / sma_vol
    return df


def add_cmf(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    vol = pd.to_numeric(df["volume"], errors="coerce")
    
    # Money Flow Multiplier = [(Close - Low) - (High - Close)] / (High - Low)
    # Handle division by zero
    hl_diff = high - low
    mfm = np.where(hl_diff == 0, 0, ((close - low) - (high - close)) / hl_diff)
    
    # Money Flow Volume
    mfv = mfm * vol
    
    # 20-period CMF
    mfv_sum = pd.Series(mfv).rolling(window=period).sum()
    vol_sum = vol.rolling(window=period).sum()
    
    df["cmf"] = mfv_sum / vol_sum
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    df["adx"] = talib.ADX(high, low, close, timeperiod=period)
    return df


def add_ema(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df[f"ema_{period}"] = talib.EMA(df["close"].astype(float), timeperiod=period)
    return df
