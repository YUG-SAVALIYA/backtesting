# RSI Supertrend Backtester

A clean Python project version of your Colab workflow.

## What this project fixes

Your notebook code has a few issues that will break or distort results:

1. The `companies` list is malformed and contains a syntax error.
2. The signal-generation block does not write `exit_time`, but the backtest requires it.
3. The backtest filters on `rsi_Daily`, but the signal-generation block does not always produce it.
4. Hardcoded Colab paths make the code unusable in an IDE or server environment.
5. Strategy logic, I/O logic, indicators, and portfolio simulation are mixed together.
6. `RSI14` is named as if it is 14-period RSI, but the code computes 21-period RSI.

This project separates those concerns so you can test, maintain, and extend it.

## Project structure

```text
trading_project/
├── pyproject.toml
├── README.md
├── config.example.json
├── run_backtest.py
├── src/
│   └── rsi_supertrend_backtester/
│       ├── cli.py
│       ├── core/
│       │   ├── config.py
│       │   ├── indicators.py
│       │   └── models.py
│       ├── io/
│       │   ├── data_loader.py
│       │   └── json_store.py
│       ├── strategies/
│       │   └── rsi_supertrend_strategy.py
│       ├── backtest/
│       │   └── portfolio.py
│       └── utils/
│           └── time_utils.py
└── tests/
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Copy `config.example.json` to `config.json` and update paths.

## Run

```bash
python run_backtest.py --config config.json
```

or

```bash
trade-backtest --config config.json
```

## Data layout expected

For each company:

- `{symbol}_125min.csv`
- `{symbol}_5min.csv`
- optional `{symbol}_day.csv`

Each CSV should include at least:

- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume` optional

## Next improvements you should consider

1. Add slippage and realistic execution assumptions.
2. Add walk-forward validation instead of one static backtest window.
3. Add unit tests for entry, stop, target, and expiry rules.
4. Add a proper metrics report with CAGR, max drawdown, win rate, expectancy.
5. Replace full-capital fill logic with risk-based position sizing.
