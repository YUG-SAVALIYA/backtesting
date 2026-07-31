import sys
import os
import pandas as pd

sys.path.insert(0, r"c:\Users\Yug\Desktop\tradesignal\backend")
sys.path.insert(0, r"c:\Users\Yug\Desktop\rsi\src")

from services.rsi.rsi_strategy import RSISupertrendStrategy as StrategyTS, StrategySettings as SettingsTS

print("Comparing strategy signal generation between projects...")

# Load daily data from companies_1yr_daily_candles.csv
df_daily_all = pd.read_csv(r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv")
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

symbols = ['AEGISLOG', 'APEXECO', 'BIKEWO', 'CARBORUNIV', 'CONSOFINVT', 'FCL', 'GUFICBIO', 'HONASA', 'KAMDHENU', 'KERNEX', 'MODISONLTD', 'OMNI', 'ONELIFECAP', 'PURPLEUTED', 'RANEHOLDIN', 'RUBICON', 'SASKEN', 'SHREEJISPG', 'SSFL', 'VENUSREM']

print("\n--- DIFFERENCES IN WEEKLY RSI CALCULATION ---")
for sym in symbols:
    df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
    if len(df_sym) < 50:
        continue
    
    # 1. tradesignal project resampling (W-SUN)
    df_idx = df_sym.set_index('datetime')
    htf_wsun = df_idx.resample('W-SUN', closed='left', label='right').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    # 2. rsi project resampling (W-FRI)
    htf_wfri = df_idx.resample('W-FRI').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
    }).dropna().reset_index()
    
    # Calculate RSI on both
    settings_ts = SettingsTS(rsi_period=14, rsi_min=65, rsi_max=90, htf_rsi_period=14, htf_rsi_min=65, htf_rsi_max=85, supertrend_period=21, supertrend_multiplier=1.5, adx_period=14, adx_min=26.0, signal_candle_range_min_pct=3.0, signal_candle_range_max_pct=8.0)
    strat_ts = StrategyTS(settings_ts)
    
    sig_wsun, _ = strat_ts.prepare_frames(df_sym.copy(), df_sym.copy(), htf_wsun)
    sig_wfri, _ = strat_ts.prepare_frames(df_sym.copy(), df_sym.copy(), htf_wfri)
    
    # Compare RSI_HTF values for dates in June-July 2026
    sub_wsun = sig_wsun[(sig_wsun['datetime'] >= '2026-06-15') & (sig_wsun['datetime'] <= '2026-07-28') & (sig_wsun['rsi'] >= 65)]
    sub_wfri = sig_wfri[(sig_wfri['datetime'] >= '2026-06-15') & (sig_wfri['datetime'] <= '2026-07-28') & (sig_wfri['rsi'] >= 65)]
    
    for idx, row in sub_wsun.iterrows():
        dt_str = str(row['datetime'])[:10]
        rsi_l = row.get('rsi')
        rsi_htf_wsun = row.get('rsi_htf')
        wfri_match = sub_wfri[sub_wfri['datetime'] == row['datetime']]
        rsi_htf_wfri = wfri_match.iloc[0].get('rsi_htf') if not wfri_match.empty else None
        
        wsun_ok = (65 <= rsi_htf_wsun <= 85) if (rsi_htf_wsun is not None and not pd.isna(rsi_htf_wsun)) else False
        wfri_ok = (65 <= rsi_htf_wfri <= 85) if (rsi_htf_wfri is not None and not pd.isna(rsi_htf_wfri)) else False
        r_wsun_str = f"{rsi_htf_wsun:.1f}" if rsi_htf_wsun is not None and not pd.isna(rsi_htf_wsun) else "None"
        r_wfri_str = f"{rsi_htf_wfri:.1f}" if rsi_htf_wfri is not None and not pd.isna(rsi_htf_wfri) else "None"
        print(f"{sym} {dt_str}: RSI_LTF={rsi_l:.1f} | RSI_HTF(W-SUN)={r_wsun_str} [pass={wsun_ok}] | RSI_HTF(W-FRI)={r_wfri_str} [pass={wfri_ok}]")
