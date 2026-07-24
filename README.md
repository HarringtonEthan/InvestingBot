# InvestingBot

A "buy the dip" stock strategy, backtested honestly.

This is a research/backtesting project, **not a live trading bot**, and
**not investment advice**. It exists to answer a specific question before
any real money is involved: does a simple dip-buying rule, optionally
filtered by a machine-learning model, actually beat just buying and
holding? The code is built so you can answer that for yourself on real
data.

## What's here

- `src/data.py` - loads daily price data. Tries Yahoo Finance
  (`yfinance`) first; if there's no network access it falls back to a
  synthetic price series calibrated to realistic equity market behavior
  (~9% annual drift, ~19% annual volatility, clustered vol regimes). Every
  place synthetic data is used, it's labeled loudly - in the console
  output and in the chart title - so it never gets mistaken for a real
  result.
- `src/features.py` - technical indicators (SMA, RSI, rolling
  volatility, drawdown-from-high) used both to define a "dip" and as ML
  features.
- `src/strategies.py` - three strategies:
  1. **Buy & hold**
  2. **Rule-based dip buy** - buy when price is >3% below its 20-day
     moving average, sell once it recovers back above the average.
  3. **ML-filtered dip buy** - same rule, but only acts on a dip if a
     model trained to predict "will this bounce?" is confident enough.
- `src/model.py` - trains a `RandomForestClassifier` on the training
  period only, with a label of "price rises >=3% within the next 10
  trading days." The confidence threshold used at test time is calibrated
  from the *training* score distribution (75th percentile of training
  scores), not hand-picked to make the test result look good.
- `src/backtest.py` - a simple long/cash backtest engine: one day of
  execution lag (no lookahead), transaction costs on every position
  change, and standard metrics (annualized return/vol, Sharpe, max
  drawdown, trade count).
- `main.py` - runs the whole pipeline end to end and saves a comparison
  chart to `results/equity_curve.png`.

## Running it

```bash
pip install -r requirements.txt
python main.py --ticker SPY --start 2015-01-01 --split 2022-01-01 --end 2024-12-31
```

`--split` is the train/test cutoff: everything before it is used only to
fit the ML filter, everything after is the held-out test period the
strategies are compared on. On a machine with normal internet access this
pulls real Yahoo Finance data automatically - nothing to change. In this
sandboxed environment, outbound requests to Yahoo Finance are blocked, so
it fell back to synthetic data automatically (you'll see this called out
in the console output and in the chart title).

## Results (synthetic-data demo run)

Since this environment can't reach Yahoo Finance, the numbers below are
from the synthetic fallback and **don't tell you anything about real
markets** - treat them as a demonstration that the pipeline runs
correctly end to end, not as a performance claim.

| Strategy | Total Return | Ann. Return | Ann. Vol | Sharpe | Max DD | Trades |
|---|---|---|---|---|---|---|
| Buy & Hold | -10.2% | -3.4% | 24.3% | -0.02 | -55.7% | 1 |
| Rule-based dip buy | -16.7% | -5.7% | 15.1% | -0.31 | -38.3% | 30 |
| ML-filtered dip buy | -22.1% | -7.7% | 13.4% | -0.53 | -31.9% | 16 |

In an earlier exploratory run against a different synthetic sample (a
milder, uptrending 2023-2024-style period), buy-and-hold came out ahead of
both dip-buying variants, and the ML filter underperformed the plain
rule-based version out of sample. That's a genuinely useful, if humbling,
result and it's reported here rather than tuned away: an ML filter losing
to a simpler rule on unseen data is one of the most common outcomes in
quantitative trading, and exactly the "fits noise, not a real edge"
failure mode worth expecting going in. The mechanics (proper time-based
train/test split, no lookahead, transaction costs modeled) are sound -
this particular rule on this particular data simply isn't a demonstrated
edge yet. Different tickers, periods, or rule parameters could tell a
different story; that's exactly what the next steps below are for.

## Before this touches real money

1. **Re-run on real data, multiple tickers, multiple periods.** One
   ticker and one train/test split proves nothing. Loop over several
   tickers (different sectors, not just SPY) and several non-overlapping
   time windows, including at least one real bear market and one real
   bull run.
2. **Walk-forward validation**, not a single train/test split - retrain
   periodically on a rolling window and test only on the period
   immediately after, repeated across the full history.
3. **Paper trade it** against a live real-time feed (e.g. Alpaca's paper
   trading API) for at least a few months before any real capital is at
   risk. A backtest that looks good can still fail live due to slippage,
   fills, and regime changes a backtest can't see.
4. **Position sizing and risk limits** - this backtest is all-in/all-out
   on a single asset. A real system needs per-trade risk limits, max
   drawdown circuit breakers, and portfolio-level diversification before
   it's sane to run with real money.
5. **Understand the failure mode going in**: this strategy is
   mean-reversion. It does reasonably in choppy, range-bound markets and
   can lose significantly in a sustained downtrend, where "the dip" just
   keeps dropping. Know that going in rather than discovering it live.

## Disclaimer

This project is for education and research. Nothing here is financial
advice, and past backtest performance - synthetic or real - does not
predict future results.
