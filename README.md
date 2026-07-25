# InvestingBot

A "buy the dip" stock strategy: backtest it, then optionally run it
automatically against a paper (fake-money) brokerage account.

**Not investment advice.** It exists to answer a specific question before
any real money is involved: does a simple dip-buying rule, optionally
filtered by a machine-learning model, actually beat just buying and
holding? The code is built so you can answer that for yourself on real
data, and then watch it trade unattended with fake money before ever
considering real money.

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
- `src/strategies.py` - four strategies:
  1. **Buy & hold**
  2. **Rule-based dip buy** - buy when price is >3% below its 20-period
     moving average, sell once it recovers back above the average
     (mean-reversion exit, independent of what you paid).
  3. **ML-filtered dip buy** - same rule, but only acts on a dip if a
     model trained to predict "will this bounce?" is confident enough.
  4. **Day trading (profit target)** - buy a dip, but sell based on your
     *actual entry price* instead of the moving average: exits once
     price is a set % above your entry (a real profit), or cuts losses
     if price falls a set % below entry first (a stop-loss, so it
     doesn't ride a sustained downtrend forever waiting for a recovery
     that may not come). This is the one wired up for the frequent,
     always-on crypto automation - see "Crypto support" below.
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
   stocks" and "Paper trade - crypto" listed. You can click into either
   one and hit **"Run workflow"** to trigger it manually right now,
   instead of waiting for the schedule, to confirm it works.
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
python live_trade.py --ticker BTC ETH SOL DOGE LTC \
  --strategy day_trading --interval 15m \
  --dip-threshold -0.02 --profit-target 0.02 --stop-loss 0.04 \
  --execute
```

This runs on 15-minute bars, buys a 2%+ dip, and sells once your
*actual* position is up 2% - or cuts it at -4% if the dip keeps falling
instead of bouncing. It's scheduled to fire every 15 minutes, every day,
automatically, via GitHub Actions - see "Running without your computer
on" above for setup.

**Worth knowing before you get excited about the frequency:** more
frequent trading means more round trips, and every round trip pays
Alpaca's crypto spread/fee (roughly 0.15-0.25% each way, so ~0.3-0.5% per
full buy-sell cycle). A 2% profit target nets a lot less than 2% after
that, and a strategy that trades often needs to be right often enough to
outrun that drag - which is exactly why backtesting this specific setup
(numbers below) before trusting it matters more, not less, at higher
frequency.

**Backtest it before trusting it** - same principle as the stock
strategy, just with intraday data and crypto-realistic fees:
```bash
python main.py --ticker BTC-USD --interval 1h \
  --start 2026-05-01 --split 2026-07-01 --end 2026-07-25 \
  --cost-bps 20 --dip-threshold -0.02 --profit-target 0.02 --stop-loss 0.04
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
