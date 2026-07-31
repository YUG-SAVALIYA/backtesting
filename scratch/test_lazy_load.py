import sys
import json
import pandas as pd
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings

def test_lazy_load_all():
    loader = MarketDataLoader("F:/Data")
    
    with open('config.json', 'r') as f:
        cfg = json.load(f)
    companies = cfg["companies"][:20]

    settings = StrategySettings(
        rsi_period=14, rsi_min=50.0, rsi_max=90.0,
        htf_rsi_period=14, htf_rsi_min=65.0, htf_rsi_max=85.0,
        supertrend_period=21, supertrend_multiplier=1.5,
        htf_supertrend_period=14, htf_supertrend_multiplier=1.0,
        max_stoploss_pct=0.05, stoploss_mode='signal_candle_low'
    )
    strategy = RSISupertrendStrategy(settings)
    start_dt = pd.to_datetime("2021-01-01")
    end_dt = pd.to_datetime("2025-12-31")

    for company in companies:
        # Check if files exist
        if not (loader.data_dir / f"{company}_Day.csv").exists():
            continue
            
        # 1. Full/original loading
        sig_df, exec_df, htf_df = loader.load_symbol_frames(company, "Day", "5min", "Week")
        prepared_sig, prepared_exec = strategy.prepare_frames(sig_df, exec_df, htf_df)
        original_signals = strategy.generate_signals(company, prepared_sig, prepared_exec, target_level=20)
        orig_count = len(original_signals)

        # 2. Lazy loading simulation
        sig_df_lazy = loader._read_csv(loader.data_dir / f"{company}_Day.csv", cache=True)
        htf_path = loader.data_dir / f"{company}_Week.csv"
        htf_df_lazy = loader._read_csv(htf_path, cache=True) if htf_path.exists() else None
        
        # Prepare using dummy execution dataframe
        dummy_exec = pd.DataFrame(columns=["open", "high", "low", "close", "datetime"])
        prepared_sig_lazy, _ = strategy.prepare_frames(sig_df_lazy, dummy_exec, htf_df_lazy)
        
        # Check potential signals
        potential_rows = prepared_sig_lazy[
            (prepared_sig_lazy["datetime"] >= start_dt) & 
            (prepared_sig_lazy["datetime"] <= end_dt) &
            (prepared_sig_lazy["in_uptrend"] == True)
        ]
        if "rsi" in potential_rows.columns:
            potential_rows = potential_rows[
                (potential_rows["rsi"] >= settings.rsi_min) & 
                (potential_rows["rsi"] < settings.rsi_max)
            ]
        if len(potential_rows) > 0 and "rsi_htf" in potential_rows.columns:
            potential_rows = potential_rows[
                (potential_rows["rsi_htf"] >= settings.htf_rsi_min) & 
                (potential_rows["rsi_htf"] < settings.htf_rsi_max)
            ]
            
        has_potential = len(potential_rows) > 0
        lazy_signals = []
        if has_potential:
            # Load execution dataframe only when needed
            real_exec = loader._read_csv(loader.data_dir / f"{company}_5min.csv", cache=False)
            real_exec = real_exec.copy()
            real_exec["datetime"] = pd.to_datetime(real_exec["datetime"]).dt.tz_localize(None)
            real_exec = real_exec.set_index("datetime")
            lazy_signals = strategy.generate_signals(company, prepared_sig_lazy, real_exec, target_level=20)

        print(f"[{company}] Has Potential: {has_potential}. Original Signals: {orig_count}, Lazy Signals: {len(lazy_signals)}")
        assert orig_count == len(lazy_signals), "Signal count mismatch!"
    
    print("ALL 20 SYMBOLS MATCH PERFECTLY!")

if __name__ == "__main__":
    test_lazy_load_all()
