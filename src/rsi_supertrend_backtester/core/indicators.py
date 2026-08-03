from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def add_rsi(df: pd.DataFrame, period: int, column_name: str) -> pd.DataFrame:
    df = df.copy()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = calculate_rma(gain, period)
    avg_loss = calculate_rma(loss, period)
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    df[column_name] = rsi
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


def calculate_rma(series: pd.Series, period: int) -> pd.Series:
    """
    TradingView exact RMA (Running Moving Average) implementation.
    Initializes using a Simple Moving Average (SMA) of the first `period` values.
    """
    rma = pd.Series(np.nan, index=series.index)
    valid_idx = series.first_valid_index()
    if valid_idx is None:
        return rma
        
    start_pos = series.index.get_loc(valid_idx)
    if len(series) - start_pos >= period:
        # Seed with SMA
        first_val = series.iloc[start_pos:start_pos+period].mean()
        rma.iloc[start_pos+period-1] = first_val
        
        # Iterate rest
        # RMA[i] = (RMA[i-1] * (period - 1) + value[i]) / period
        alpha = 1 / period
        series_np = series.to_numpy()
        rma_np = rma.to_numpy(copy=True)
        for i in range(start_pos+period, len(series_np)):
            if not np.isnan(series_np[i]):
                rma_np[i] = (series_np[i] * alpha) + (rma_np[i-1] * (1 - alpha))
        rma = pd.Series(rma_np, index=series.index)
        
    # Fallback to EWM if not enough data
    return rma.fillna(series.ewm(alpha=1/period, adjust=False).mean())


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    tr_series = tr(df)
    df["ATR"] = calculate_rma(tr_series, period)
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
    
    high_diff = df['high'].diff()
    low_diff = -df['low'].diff()
    
    pos_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
    neg_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    
    smoothed_tr = calculate_rma(tr, period)
    smoothed_pos_dm = calculate_rma(pd.Series(pos_dm, index=df.index), period)
    smoothed_neg_dm = calculate_rma(pd.Series(neg_dm, index=df.index), period)
    
    pos_di = 100 * (smoothed_pos_dm / smoothed_tr)
    neg_di = 100 * (smoothed_neg_dm / smoothed_tr)
    
    dx = 100 * np.abs(pos_di - neg_di) / (pos_di + neg_di + 1e-10)
    adx = calculate_rma(dx, period)
    
    df["adx"] = adx
    return df


def add_ema(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df[f"ema_{period}"] = talib.EMA(df["close"].astype(float), timeperiod=period)
    return df
