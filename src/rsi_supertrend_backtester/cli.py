from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsi_supertrend_backtester.backtest.portfolio import PortfolioBacktester
from rsi_supertrend_backtester.core.config import load_config
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader
from rsi_supertrend_backtester.io.json_store import save_signals
from rsi_supertrend_backtester.strategies.rsi_supertrend_strategy import RSISupertrendStrategy, StrategySettings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RSI Supertrend signal generation and backtest")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    loader = MarketDataLoader(config.data_dir)
    strategy = RSISupertrendStrategy(
        StrategySettings(
            rsi_period=config.signal_settings.rsi_period,
            htf_rsi_period=config.signal_settings.htf_rsi_period,
            supertrend_period=config.signal_settings.supertrend_period,
            supertrend_multiplier=config.signal_settings.supertrend_multiplier,
            entry_lookahead_bars=config.signal_settings.entry_lookahead_bars,
            max_stoploss_pct=config.signal_settings.max_stoploss_pct,
            
        )
    )

    print("Generating signals...")
    for company in config.companies:
        signal_df, execution_df, htf_df = loader.load_symbol_frames(
            company,
            config.signal_settings.signal_timeframe_file_suffix,
            config.signal_settings.execution_timeframe_file_suffix,
            config.signal_settings.htf_timeframe_file_suffix,
        )

        signal_df, execution_df = strategy.prepare_frames(signal_df, execution_df, htf_df)
        
        signal_df = signal_df[
            (signal_df["datetime"] >= config.backtest_settings.start_date) & 
            (signal_df["datetime"] <= config.backtest_settings.end_date)
        ].copy()

        # The original code had a loop for target_levels, but the instruction implies a single target_level from config.backtest_settings
        # Assuming the instruction intends to replace the loop with a single call using config.backtest_settings.target_level
        signals = strategy.generate_signals(
            company=company, # Changed from 'symbol' to 'company' to match the loop variable
            signal_df=signal_df,
            execution_df=execution_df,
            target_level=config.backtest_settings.target_level,
        )
        target_level = config.backtest_settings.target_level # Define target_level for the output path
        out_file = config.output_dir / company / "signals" / f"signals_target_{target_level}.json"
        save_signals(out_file, signals)
        print(f"{company} | target {target_level} | signals: {len(signals)}")

    print("Running portfolio backtest...")
    portfolio = PortfolioBacktester(
        initial_capital=config.portfolio_settings.initial_capital,
        fee_rate=config.portfolio_settings.fee_rate,
        mtf_enabled=config.portfolio_settings.mtf_enabled,
        mtf_leverage=config.portfolio_settings.mtf_leverage,
        mtf_daily_rate=config.portfolio_settings.mtf_daily_rate,
        cap_fraction=config.portfolio_settings.cap_fraction,
        rsi_filter=config.portfolio_settings.rsi_filter,
        htf_rsi_filter=config.portfolio_settings.htf_rsi_filter,
    )

    trades_by_company = {}
    for company in config.companies:
        company_trades = []
        for target_level in config.signal_settings.target_levels:
            path = config.output_dir / company / "signals" / f"signals_target_{target_level}.json"
            company_trades.extend(portfolio.load_filtered_trades(path))
        trades_by_company[company] = company_trades

    snapshots = portfolio.simulate(trades_by_company)
    snapshots_path = config.output_dir / "portfolio_snapshots.json"
    snapshots_path.write_text(json.dumps(snapshots, indent=2))
    print(f"Saved portfolio snapshots to {snapshots_path}")

if __name__ == '__main__':
    main()
