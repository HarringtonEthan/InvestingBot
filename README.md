# InvestingBot

A "buy the dip" stock and crypto strategy: backtest it, search for better
settings systematically, then optionally run it automatically against a
paper (fake-money) brokerage account.

**Not investment advice.** It exists to answer a specific question before
any real money is involved: do these dip-buying rules actually beat just
buying and holding? So far, on real recent data, the honest answer is
**no** - see "Current live status" below for specifics. The code is built
so you can keep answering that for yourself on real data, and only
consider real money once something actually demonstrates an edge.

## Current live status (as of this writing)

This section exists so nobody - including future us - has to reverse
engineer what's actually running from workflow files. Update it whenever
the live configuration changes.

- **Crypto: live and automated, rule-based, no ML.** An external free
  scheduler ([cron-job.org](https://cron-job.org)) calls GitHub's API
  every 5 minutes to run `.github/workflows/paper-trade-crypto.yml`,
  which runs `live_trade.py --strategy day_trading` against **BTC, ETH,
  SOL, DOGE, LTC, AVAX, LINK, XRP, DOT** on 5-minute bars: buy a 1.0%
  dip, sell at +1.0% profit or -3.0% stop-loss. These are `optimize.py`'s
  best average-across-all-9-coins combo (replacing the earlier
  -0.5%/+0.8%/-1.5%, which it beat on the tested window) - both still
  lost money on average over that period, this one just lost less, and
  it hasn't been re-validated on a different time window yet. This does
  not depend on GitHub's own cron (which we found unreliable - see
  below) or on any computer being on.
- **Stocks: live and automated, ML-filtered, with periodic retraining.**
  The stock workflow (`paper-trade-stocks.yml`) runs `--strategy
  ml_filtered` on SPY/AAPL/QQQ instead of `rule_based`. Unlike every
  other strategy in this project, this one actually persists a model
  between runs: a separate workflow, `retrain-stock-model.yml` (via
  `train_stock_model.py`), pools recent SPY/AAPL/QQQ data into one
  `RandomForestClassifier`, saves it to `models/stock_model.pkl`, and
  commits it back to the repo; `live_trade.py` loads that saved model on
  every run instead of retraining from scratch. Two cron-job.org jobs
  now drive both workflows the same way one already drives crypto -
  `retrain-stock-model.yml` weekly, `paper-trade-stocks.yml` daily near
  market close - confirmed working: a model has been trained (see
  `logs/retrain_log.csv`) and `logs/trade_log.csv` shows real
  `ml_filtered` decisions for SPY/AAPL/QQQ. See "Machine learning: what
  it actually does" in "What's here" below for what this does and
  doesn't mean - in particular, this setup has no real-data track record
  yet, so "automated" here is not the same claim as "proven to work."
  There's also still an open QQQ paper position from the old
  `rule_based` manual test (back before this switch) that hasn't been
  re-evaluated since - worth checking the Alpaca paper dashboard for it.
- **Local Windows Task Scheduler: should be disabled.** Both local tasks
  were used earlier for testing and troubleshooting; cron-job.org now
  handles crypto automation instead. Leaving a local task enabled
  alongside cron-job.org would double-trade the same account.
- **Bollinger breakout: implemented, not deployed.** `--strategy
  bollinger_breakout` exists (see `src/strategies.py`) but isn't wired
  into any live workflow. Backtested on 5-minute crypto bars during a
  choppy (non-trending) stretch, it performed far worse than the other
  strategies - expected, since it's a trend-following design meant for
  slower timeframes and genuinely trending markets, not what it was
  tested against.

## What's here

- `src/data.py` - loads price data at daily or intraday resolution
  (`--interval 1d`, `1h`, `15m`, etc.). Tries Yahoo Finance (`yfinance`)
  first; if there's no network access it falls back to a synthetic price
  series calibrated to realistic market behavior (~9% annual drift, ~19%
  annual volatility, clustered vol regimes), generated at whatever bar
  frequency was requested. Every place synthetic data is used, it's
  labeled loudly - in the console output and in the chart title - so it
  never gets mistaken for a real result.
- `src/features.py` - technical indicators (SMA, RSI, rolling
  volatility, drawdown-from-high) used both to define a "dip" and as ML
  features. Windows are defined in bars, not calendar days, so the same
  code produces a 20-day trend on daily data or a 20-hour trend on hourly
  data.
- `src/strategies.py` - five strategies:
  1. **Buy & hold**
  2. **Rule-based dip buy** - buy when price is >3% below its 20-period
     moving average, sell once it recovers back above the average
     (mean-reversion exit, independent of what you paid). Note: this
     3% threshold is hardcoded in `src/strategies.py` and is *not*
     connected to the `--dip-threshold` CLI flag (only "Day trading"
     below uses that flag) - on real recent crypto/5-minute data, moves
     rarely reach 3%, so this strategy currently shows ~0 trades there.
  3. **ML-filtered dip buy** - same rule (same hardcoded 3% dip, same
     caveat), but only acts on a dip if a model trained to predict "will
     this bounce?" is confident enough.
  4. **Day trading (profit target)** - buy a dip, but sell based on your
     *actual entry price* instead of the moving average: exits once
     price is a set % above your entry (a real profit), or cuts losses
     if price falls a set % below entry first (a stop-loss, so it
     doesn't ride a sustained downtrend forever waiting for a recovery
     that may not come). This is the one wired up for the frequent,
     always-on crypto automation - see "Crypto support" below.
  5. **Bollinger breakout** - a trend-following (not mean-reversion) bet:
     buy when price breaks above its upper Bollinger Band while also
     above a long-term trend average, sell when it falls back below the
     middle band. Implemented but not wired into any live workflow - see
     "Current live status" above for why.
- `src/model.py` - trains a `RandomForestClassifier` on the training
  period only, with a label of "price rises >=3% within the next 10
  trading days." The confidence threshold used at test time is calibrated
  from the *training* score distribution (75th percentile of training
  scores), not hand-picked to make the test result look good.

  **Machine learning: what it actually does (and doesn't).** This is the
  only ML in the project, and only used by `ml_filtered` - `rule_based`,
  `day_trading` (the live crypto strategy), and `bollinger_breakout` are
  pure rules, no model involved. Important to be clear-eyed about:
  - By default (in a backtest, or via `main.py`) it does not "learn" in
    an ongoing/online sense: `train_model()` fits a brand-new
    `RandomForestClassifier` from scratch on whatever training window
    you give it, uses it once, and discards it.
  - The **live stock workflow is the one exception**: it uses
    `train_model_multi()` + `src/model_store.py` to save a model to
    `models/stock_model.pkl` on a schedule (`train_stock_model.py`, see
    "Current live status" above) and `live_trade.py` loads that saved
    model instead of retraining inline. That's real persistence between
    runs - but it's still periodic batch retraining (e.g. weekly), not
    the model updating itself after every trade the way "a bot that
    learns" often implies.
  - It has never been shown to beat the plain rule-based version. In the
    one direct real-data comparison run in this project so far, the ML
    filter underperformed the plain rule-based strategy out of sample -
    a common and expected outcome (a filter can easily fit noise in the
    training window rather than a real pattern). The switch to live
    ml_filtered for stocks is a bet that periodic retraining on pooled
    multi-ticker data behaves differently - not yet proven, since that
    setup has no real-data track record yet.
  - Its dip threshold has the same hardcoded-3%/real-volatility mismatch
    described above. This matters less for stocks on daily bars (where
    3% moves are plausible) than it would on 5-minute crypto data (where
    it would fire on almost nothing) - one more reason ML stayed off
    crypto and went to stocks instead.
- `src/backtest.py` - a simple long/cash backtest engine: one day of
  execution lag (no lookahead), transaction costs on every position
  change, and standard metrics (annualized return/vol, Sharpe, max
  drawdown, trade count).
- `src/model_store.py` / `train_stock_model.py` - saves/loads a trained
  model to/from `models/stock_model.pkl` so it can be trained once,
  periodically, and reused across live runs instead of being refit from
  scratch every time. See "Machine learning" above and
  `.github/workflows/retrain-stock-model.yml`.
- `main.py` - runs the whole pipeline end to end and saves a comparison
  chart to `results/equity_curve.png`.
- `src/broker.py` / `live_trade.py` - automated trading against an
  Alpaca account. Defaults to Alpaca's **paper** endpoint (fake money,
  real live prices) and refuses to run at all if only synthetic data is
  available. See "Automated paper trading" below.

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

## Automated paper trading

This runs the strategy against a real broker automatically, so you don't
have to click anything - but against **paper** trading by default, which
uses fake money on a real live account. No real cash is at risk until you
deliberately flip a switch described at the end of this section.

### 1. Create a free Alpaca paper account

1. Go to https://alpaca.markets and sign up (free).
2. Once logged in, make sure you're on the **Paper Trading** dashboard
   (it's the default view, and is separate from any live account - Alpaca
   won't let you fund it with a real bank account).
3. Go to **API Keys** and generate a paper key pair. You'll get an
   `API Key ID` and a `Secret Key` - copy both immediately, the secret is
   only shown once.

### 2. Configure your keys

```bash
cp .env.example .env
```
Edit `.env` and paste in your key ID and secret:
```
ALPACA_API_KEY=your_paper_api_key_id
ALPACA_SECRET_KEY=your_paper_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```
`.env` is git-ignored - never commit it.

### 3. Try it manually first (dry run, no orders placed)

```bash
python live_trade.py --ticker SPY --strategy rule_based
```
This prints what it *would* do (buy/sell/hold) based on today's real
price data and your actual paper account position, but doesn't place an
order yet. Run it a few times on different days to get a feel for it.

`--ticker` takes one or more symbols, space-separated:
```bash
python live_trade.py --ticker SPY AAPL QQQ --strategy rule_based
```
Each ticker gets its own independent buy/sell/hold decision. If more than
one signals BUY in the same run, available cash is split evenly across
them rather than the first one spending the whole account (pass
`--max-notional 1000` to additionally cap the dollar amount per buy).

### 4. Let it actually place paper orders

```bash
python live_trade.py --ticker SPY --strategy rule_based --execute
```
This places the order for real against your **paper** account. Check the
Alpaca paper dashboard to see the fill. Every run also appends a line to
`logs/trade_log.csv` (git-ignored) so you have a record of every decision
the bot made, executed or not.

### 5. Make it run automatically, on a schedule

The strategy is a once-a-day decision (it's based on daily closing
prices), so schedule it to run once a day, a few minutes before market
close (4pm ET / 3:55pm ET), on whatever machine you leave running:

**macOS/Linux (cron):**
```bash
crontab -e
# Add a line like this (adjust the path and time; cron uses your system's local time):
55 15 * * 1-5 cd /path/to/InvestingBot && /usr/bin/python3 live_trade.py --ticker SPY AAPL QQQ --strategy rule_based --execute >> logs/cron.log 2>&1
```

**Windows (Task Scheduler):** create a new task that runs
`live_trade.py --ticker SPY AAPL QQQ --strategy rule_based --execute` in
the `InvestingBot` folder, triggered daily on weekdays at 3:55pm.

Your laptop needs to be on and awake at that time for cron/Task Scheduler
to fire. If that's not realistic, see "Running without your computer on"
below.

### Running without your computer on (GitHub Actions)

This repo includes `.github/workflows/paper-trade-stocks.yml` and
`.github/workflows/paper-trade-crypto.yml`, which let GitHub run the bot
for you on their own servers, for free, on the same schedule described
above - no computer of yours needs to be on at all.

**Setup:**
1. On GitHub, go to your repo -> **Settings -> Actions -> General ->
   Workflow permissions**, select **"Read and write permissions,"** and
   save. (This lets the workflow commit the trade log back to the repo
   after each run.)
2. Go to **Settings -> Secrets and variables -> Actions -> New repository
   secret** and add two secrets: `ALPACA_API_KEY` and
   `ALPACA_SECRET_KEY`, using the same paper-trading values from your
   `.env` file. These are encrypted by GitHub and never shown in logs.
3. Push this branch (or merge it into your default branch) if you
   haven't already - scheduled workflows only run from the repo's
   default branch.
4. Go to the **Actions** tab on GitHub, and you should see "Paper trade -
   stocks," "Paper trade - crypto," and "Retrain stock ML model" listed.
   You can click into any of them and hit **"Run workflow"** to trigger
   it manually right now, instead of waiting for the schedule, to
   confirm it works.
5. Every run appends to `logs/trade_log.csv` and the workflow
   automatically commits that update back to the repo, so `git pull`
   locally will show new commits with a "Log ... trading run" message
   over time. That's the automated bot committing its own log, not you.

**Important - avoid double-trading:** once GitHub Actions is confirmed
working, **turn off your local Windows Task Scheduler tasks** (or the
cron jobs, if you're on Mac/Linux). If both your PC and GitHub Actions
are scheduled to run at the same time against the same Alpaca account,
you'd get duplicate orders - each one independently deciding to buy,
unaware the other already did. Only one automation path should be active
against a given account at a time. To disable in Task Scheduler: find the
task, right-click -> Disable (or Delete, once you're confident GitHub
Actions is working reliably).

### Crypto support

`--ticker` also accepts crypto: just pass the base symbol (`BTC`, `ETH`,
`SOL`, `DOGE`, `LTC`, and others - see `KNOWN_CRYPTO_BASES` in
`src/symbols.py`). It's auto-detected and mapped to the right format for
both Yahoo Finance (`BTC-USD`) and Alpaca (`BTC/USD`) automatically.

**Live crypto trading pulls price data from Alpaca, not Yahoo Finance**
(`src/alpaca_data.py`) - Yahoo's intraday crypto bars can silently go
stale for hours without erroring (serving an old price as if it were
current), so `live_trade.py` uses Alpaca's own crypto market data
instead: the same venue trades actually execute against, and every
fetch is checked against a staleness threshold - if the latest bar is
older than expected for the requested interval, that ticker is skipped
for the run rather than traded on outdated data. Backtesting (`main.py`)
still uses Yahoo Finance, since staleness doesn't matter for historical
data and Yahoo's history window is much longer than Alpaca's crypto feed.

**Crypto trades 24/7**, unlike stocks, and the GitHub Actions crypto
workflow (`.github/workflows/paper-trade-crypto.yml`) is configured for
day trading rather than the once-a-day daily-close strategy:

```bash
python live_trade.py --ticker BTC ETH SOL DOGE LTC AVAX LINK XRP DOT \
  --strategy day_trading --interval 5m \
  --dip-threshold -0.01 --profit-target 0.01 --stop-loss 0.03 \
  --execute
```

This runs on 5-minute bars, buys a 1.0%+ dip, and sells once your
*actual* position is up 1.0% - or cuts it at -3.0% if the dip keeps
falling instead of bouncing. These are `optimize.py`'s best
average-across-all-9-coins combo as of this writing (see "Searching for
better thresholds" below) - re-run that search periodically as more real
trade history accumulates, since "best on the window tested" is not a
permanent property.

**Thresholds should match real observed volatility, not be picked
arbitrarily.** The original 2%/2%/4% thresholds never fired a single
trade in practice - actual short-term crypto moves during a live check
were closer to 0.05-0.2% over 5-minute windows, so a 2% dip essentially
never happens on that timeframe. Before changing these numbers, check
what the market is actually doing (`logs/trade_log.csv` has real price
history) rather than guessing.

**Worth knowing before you tighten these further:** more frequent
trading means more round trips, and every round trip pays Alpaca's
crypto spread/fee (roughly 0.15-0.25% each way, so ~0.3-0.5% per full
buy-sell cycle). If `--profit-target` is smaller than that fee drag, the
strategy loses money **on average even when directionally correct** -
there's a real floor below which "more trades" just means "more fee
payments," not more profit. The 0.8% target above has been kept
deliberately above that floor; going much lower trades against the fee
structure, not with it.

**Backtest it before trusting a threshold change** - same principle as
the stock strategy, just with intraday data and crypto-realistic fees:
```bash
python main.py --ticker BTC-USD --interval 1h \
  --start 2026-05-01 --split 2026-07-01 --end 2026-07-25 \
  --cost-bps 20 --dip-threshold -0.01 --profit-target 0.01 --stop-loss 0.03
```
(Yahoo Finance only keeps a limited window of intraday history, so keep
`--start` recent rather than reaching back years like the daily stock
backtest does.)

If you'd rather run stocks and crypto with matching strategies/settings
instead, both workflows accept the same `--strategy`, `--interval`,
`--dip-threshold`, `--profit-target`, and `--stop-loss` flags - edit the
`run` line in either `.github/workflows/paper-trade-*.yml` file to
change what it does.

Both workflows write to the same `logs/trade_log.csv`, so you can tell
stock vs. crypto decisions apart by the `ticker` column, and day-trading
decisions additionally log `entry_price`/`gain_pct` so you can see the
real unrealized P&L behind each sell.

### Stock automation: ML with periodic retraining

Stocks run a different strategy than crypto on purpose - `ml_filtered`
instead of the rule-based `day_trading`, so this project has one live
example of each approach to actually compare over time, and so the ML
path gets exercised somewhere: crypto's 5-minute bars are too fast for
the model's hardcoded 3% dip threshold to fire on (see "Machine
learning" above), but daily stock bars are within range of it.

`live_trade.py --strategy ml_filtered` loads whatever model is saved at
`--model-path` (default `models/stock_model.pkl`) rather than training
one on the spot. That file is produced by a **separate** workflow,
`.github/workflows/retrain-stock-model.yml`, which runs
`train_stock_model.py` - it pools recent SPY/AAPL/QQQ data into one
model (a setting that only works on one stock isn't a real edge, same
principle as `optimize.py`) and commits the result back to the repo.
This is what makes the live stock model "learn" in the sense of updating
over time, instead of being fixed at the moment this code was written:

```bash
python train_stock_model.py --ticker SPY AAPL QQQ --lookback-days 730
```

**Setup, in order:**
1. Complete the GitHub Actions setup above (secrets, write permissions)
   if you haven't already - `retrain-stock-model.yml` needs the same
   write permission to commit the model file that the trade-log commits
   use, though it doesn't need the Alpaca secrets since it only trains,
   never trades.
2. Go to the **Actions** tab -> **"Retrain stock ML model"** -> **"Run
   workflow"** once, manually, to produce the first `models/stock_model.pkl`.
   Until this has run at least once, `live_trade.py --strategy
   ml_filtered` falls back to training inline from just that run's data
   (it prints a warning when this happens) rather than failing outright.
3. Point cron-job.org (or any external scheduler) at both stock
   workflows' `workflow_dispatch` endpoints, the same way it's already
   wired up for crypto - see "Current live status" at the top of this
   README for why GitHub's own `schedule:` trigger isn't enough on its
   own. A reasonable starting cadence: `retrain-stock-model.yml` weekly,
   `paper-trade-stocks.yml` daily near market close.

Every retrain also appends a row to `logs/retrain_log.csv` (tickers
used, training window, row count, calibrated threshold) so you can see
the model's history over time, the same way `logs/trade_log.csv` tracks
trade history.

### Searching for better thresholds (optimize.py)

Hand-picking a dip/profit/stop combination and hoping it's good is a form
of overfitting if you just keep nudging numbers until one backtest looks
positive. `optimize.py` instead sweeps a whole grid of combinations
across multiple tickers at once and reports the **average** across all of
them - a setting that only works on one coin isn't a real edge, it's
luck:

```bash
python optimize.py --ticker BTC-USD ETH-USD SOL-USD DOGE-USD LTC-USD AVAX-USD LINK-USD XRP-USD DOT-USD \
  --interval 5m --start 2026-05-27 --split 2026-07-11 --end 2026-07-25 --cost-bps 20 \
  --dip-values=-0.003,-0.005,-0.008,-0.01,-0.015,-0.02 \
  --profit-values 0.005,0.008,0.01,0.015,0.02 \
  --stop-values 0.01,0.015,0.02,0.03
```
(Note the `=` in `--dip-values=...` - without it, argparse mistakes the
leading `-` for a new flag.)

It prints the top combinations by average return and writes the full
grid to `results/param_sweep.csv`. **Before trusting whatever comes out
on top:** open that CSV and check whether nearby parameter values also
perform reasonably well (a real signal) or whether the winner is an
isolated spike surrounded by much worse neighbors (almost always noise
from testing many combinations - exactly the "parameter sensitivity
check" step that separates a real strategy from an overfit one). Even a
robust-looking winner should still be re-validated on a later, different
time window before it's trusted with anything beyond fake money -
finding good settings on one stretch of history is the easy part;
knowing they'll hold up going forward is the part that actually matters.

### 6. Going live (real money) - deliberately, later

`live_trade.py` has two independent locks against ever touching a real
account by accident:
1. `ALPACA_BASE_URL` must be explicitly changed to Alpaca's live endpoint
   (`https://api.alpaca.markets`) with real (non-paper) API keys.
2. You must also pass `--i-understand-this-is-live` on the command line.

Both are required; neither alone will trade real money. Don't flip these
until you've watched the paper version run unattended for a meaningful
stretch (weeks to months) and you understand and accept its drawdown
behavior from the backtest above.

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
