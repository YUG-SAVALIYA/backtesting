from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SignalSettings:
    signal_timeframe_file_suffix: str
    execution_timeframe_file_suffix: str
    htf_timeframe_file_suffix: str
    rsi_period: int
    htf_rsi_period: int
    supertrend_period: int
    supertrend_multiplier: float
    entry_lookahead_bars: int
    max_stoploss_pct: float
    target_levels: list[int]
    look_forward_limit: int


@dataclass
class PortfolioSettings:
    initial_capital: float
    fee_rate: float
    mtf_enabled: bool
    mtf_leverage: float
    mtf_daily_rate: float
    cap_fraction: float
    rsi_filter: tuple[float, float]
    htf_rsi_filter: tuple[float, float]


@dataclass
class AppConfig:
    data_dir: Path          # used by the Backtester
    scanner_data_dir: Path  # used by the Scanner (Live_Data)
    output_dir: Path
    companies: list[str]
    start_date: str
    end_date: str
    signal_settings: SignalSettings
    portfolio_settings: PortfolioSettings


def load_config(path: str | Path) -> AppConfig:
    import re
    text = Path(path).read_text()
    # Support basic # comments for user convenience
    lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
    clean_text = "\n".join(lines)
    # Support trailing commas for user convenience
    clean_text = re.sub(r",\s*([\]}])", r"\1", clean_text)
    raw = json.loads(clean_text)
    return AppConfig(
        data_dir=Path(raw["data_dir"]),
        scanner_data_dir=Path(raw.get("scanner_data_dir", raw["data_dir"])),
        output_dir=Path(raw["output_dir"]),
        companies=raw["companies"],
        start_date=raw["start_date"],
        end_date=raw["end_date"],
        signal_settings=SignalSettings(**raw["signal_settings"]),
        portfolio_settings=PortfolioSettings(
            **{
                **raw["portfolio_settings"],
                "rsi_filter": tuple(raw["portfolio_settings"]["rsi_filter"]),
                "htf_rsi_filter": tuple(raw["portfolio_settings"]["htf_rsi_filter"]),
            }
        ),
    )
