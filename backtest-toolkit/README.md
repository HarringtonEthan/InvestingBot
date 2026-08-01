# Backtest & Walk-Forward Toolkit

A Python toolkit for backtesting rule-based and ML-filtered trading strategies without the mistakes that quietly make most home-built backtests lie to you: lookahead bias, unrealistic transaction costs, and "I tuned it until the number looked good" overfitting.

Works out of the box against **free Yahoo Finance data** — no broker account, no API key, no paid data subscription required. An optional Alpaca integration is included if you want deeper intraday history than Yahoo's ~60-day window allows.

## What's inside

- **`src/backtest.py`** — the core engine. Every position decision is lagged one full bar before it affects P&L (no lookahead), and every position change pays a configurable transaction cost in basis points.
- **`src/features.py`** — technical indicators (SMA, RSI, rolling volatility, drawdown-from-high) computed strictly from past data.
- **`src/strategies.py`** — five ready-to-use strategies: buy-and-hold, rule-based dip buying, day-trading dip buying (profit target / stop-loss), Bollinger Band breakout, and an ML-gated dip filter.
- **`src/model.py`** — an optional RandomForest "dip filter" you can train on your own data, with correct handling of the label-leakage bug that trips up most from-scratch implementations (rows without enough future data to know the true answer are excluded, not silently mislabeled).
- **`main.py`** — run all five strategies against a ticker and get a comparison chart.
- **`optimize.py`** — grid-search parameters across multiple tickers at once, scored by the average across tickers (not the best single ticker) so you don't mistake luck for an edge.
- **`walk_forward.py`** — splits your date range into several sequential, non-overlapping windows and re-tests the same fixed parameters on each one independently, so you can tell whether a strategy holds up over time or just got lucky once.
- **`tests/`** — a real test suite (`pytest`) covering the exact bug classes that quietly wreck home-built backtests: lookahead bias, label leakage, RSI edge cases, and window-splitting correctness.

## Quick start

```bash
pip install -r requirements.txt

# Compare 5 strategies on SPY, 2015-2024, with a 2022 train/test split
python main.py --ticker SPY --start 2015-01-01 --split 2022-01-01 --end 2024-12-31

# Grid-search dip/exit thresholds across several tickers
python optimize.py --ticker AAPL MSFT GOOG --start 2018-01-01 --split 2023-01-01 --end 2024-12-31 --interval 1d

# Walk-forward validate a candidate on 6 sequential windows
python walk_forward.py --ticker AAPL MSFT GOOG --strategy rule_based --dip-threshold -0.015 --exit-threshold 0.02 --start 2018-01-01 --end 2024-12-31 --windows 6 --interval 1d

# Run the test suite
pytest
```

Every command above works with zero configuration — no `.env`, no API keys. Add `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (a free Alpaca paper-trading account is enough) only if you want to validate an intraday strategy over a longer window than Yahoo Finance's free ~60-day intraday history allows.

## Why this exists (read this before trusting any backtest — including this one)

Most home-built backtests fail in one of three ways, silently:

1. **Lookahead bias.** A feature or decision accidentally uses information that wouldn't have been available yet at that point in time. This toolkit's backtest engine enforces a one-bar execution lag on every position change, and the included test suite specifically checks for this class of bug.
2. **Unrealistic costs.** A strategy that "backtests great" with zero transaction costs can be a net loser once real spread and fees are included, especially for strategies that trade often. Every backtest here charges a configurable cost in basis points on every position change — set it realistically for your asset class (crypto fees run meaningfully higher than stocks).
3. **Overfitting via optimization.** Testing 500 parameter combinations and picking the best one on the same data you tested it on will always find something that looks good — that's a property of testing 500 things, not evidence of a real edge. `optimize.py` scores across multiple tickers (not one), and `walk_forward.py` re-tests the winner on sequential, non-overlapping time windows it hasn't "seen" as a group, so you can tell a real, consistent edge from a lucky spike.

This toolkit gives you the tools to avoid all three — it doesn't guarantee any strategy you build with it will be profitable. No backtest, however careful, can promise that live results will match it. Treat every result as a hypothesis to keep testing, not a conclusion.

## License

See `LICENSE.txt`. Single-buyer license: use it for your own trading research, on your own accounts, for as many strategies as you like. Not for resale or redistribution of the toolkit itself.

## Support

Questions or issues: reach out via the platform you purchased this through.
