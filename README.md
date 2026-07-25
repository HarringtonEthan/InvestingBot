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
to fire. If that's not realistic, the next step once you trust this is
moving it to a small always-on server or a cloud scheduled job (e.g. a
$5-6/mo VM, or a serverless cron trigger) - happy to help set that up once
you're at that point.

### Crypto support

`--ticker` also accepts crypto: just pass the base symbol (`BTC`, `ETH`,
`SOL`, `DOGE`, `LTC`, and others - see `KNOWN_CRYPTO_BASES` in
`src/symbols.py`). It's auto-detected and mapped to the right format for
both Yahoo Finance (`BTC-USD`) and Alpaca (`BTC/USD`) automatically:

```bash
python live_trade.py --ticker BTC ETH SOL DOGE LTC --strategy rule_based --execute
```

Stocks and crypto can be mixed in the same command - cash still splits
evenly across whichever ones signal BUY that run.

**Crypto trades 24/7**, unlike stocks - there's no market close to time
a daily check around, and price keeps moving through the night and on
weekends. That means checking more often than once a day is actually
useful here (the strategy still looks at daily-average indicators, but
"today's close" is really "right now" for crypto, so an hourly check can
catch a dip/recovery signal mid-day instead of waiting until tomorrow).
Set this up as a **second, separate** scheduled task from your stock one,
running every hour, every day (including weekends):

**macOS/Linux (cron)** - add a second line to `crontab -e`:
```
0 * * * * cd /path/to/InvestingBot && /usr/bin/python3 live_trade.py --ticker BTC ETH SOL DOGE LTC --strategy rule_based --execute >> logs/cron_crypto.log 2>&1
```

**Windows (Task Scheduler)** - create a second task (e.g.
`InvestingBot Crypto Hourly`):
1. **Triggers tab:** New → "Begin the task: **Daily**" → set it to start
   at 12:00 AM and repeat **every day** (not just weekdays) → check
   **"Repeat task every: 1 hour"** → set "for a duration of" to
   **"Indefinitely."**
2. **Actions tab:** same Program/script (path to `python.exe`) and
   "Start in" (project folder) as your stock task, but with these
   arguments instead:
   ```
   live_trade.py --ticker BTC ETH SOL DOGE LTC --strategy rule_based --execute
   ```

Both tasks write to the same `logs/trade_log.csv`, so you can tell stock
vs. crypto decisions apart by the `ticker` column.

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
