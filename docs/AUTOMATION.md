# Automation: GitHub Actions and cron-job.org setup

[← Back to README](../README.md)

This runs the strategy against a real broker automatically, so I don't
have to click anything - but against **paper** trading by default, which
uses fake money on a real live account. No real cash is at risk until I
deliberately flip a switch described in `docs/RISK.md`. If you haven't
completed "Setup" in the main README yet (installing Python/git,
cloning, installing dependencies), do that first.

## 1. Create a free Alpaca paper account

1. Go to https://alpaca.markets and sign up (free).
2. Once logged in, make sure you're on the **Paper Trading** dashboard
   (it's the default view, and is separate from any live account - Alpaca
   won't let you fund it with a real bank account).
3. Go to **API Keys** and generate a paper key pair. You'll get an
   `API Key ID` and a `Secret Key` - copy both immediately, the secret is
   only shown once.

## 2. Configure your keys

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

## 3. Try it manually first (dry run, no orders placed)

```bash
python live_trade.py --ticker SPY --strategy rule_based
```
This prints what it *would* do (buy/sell/hold) based on today's real
price data and my actual paper account position, but doesn't place an
order yet. Run it a few times on different days to get a feel for it.

`--ticker` takes one or more symbols, space-separated:
```bash
python live_trade.py --ticker SPY AAPL QQQ --strategy rule_based
```
Each ticker gets its own independent buy/sell/hold decision. If more than
one signals BUY in the same run, available cash gets split evenly across
them rather than the first one spending the whole account (pass
`--max-notional 1000` to additionally cap the dollar amount per buy).

## 4. Let it actually place paper orders

```bash
python live_trade.py --ticker SPY --strategy rule_based --execute
```
This places the order for real against my **paper** account. I check the
Alpaca paper dashboard to see the fill. See "Logs and the trade dashboard"
below for what gets recorded and where.

## 5. Make it run automatically, on a schedule

The strategy is a once-a-day decision (it's based on daily closing
prices), so I schedule it to run once a day, a few minutes before market
close (4pm ET / 3:55pm ET), on whatever machine I leave running:

**macOS/Linux (cron):**
```bash
crontab -e
# Add a line like this (adjust the path and time; cron uses your system's local time):
55 15 * * 1-5 cd /path/to/InvestingBot && /usr/bin/python3 live_trade.py --ticker SPY AAPL QQQ --strategy rule_based --execute >> logs/cron.log 2>&1
```

**Windows (Task Scheduler):** create a new task that runs
`live_trade.py --ticker SPY AAPL QQQ --strategy rule_based --execute` in
the `InvestingBot` folder, triggered daily on weekdays at 3:55pm.

My laptop needs to be on and awake at that time for cron/Task Scheduler
to fire. If that's not realistic, see "Running without your computer on"
below.

## Running without your computer on (GitHub Actions)

This repo includes `.github/workflows/paper-trade-stocks.yml` and
`.github/workflows/paper-trade-crypto.yml`, which let GitHub run the bot
for me on their own servers, for free, on the same schedule described
above - no computer of mine needs to be on at all.

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
5. Each run may append to `logs/equity_log_crypto.csv`/`logs/equity_log_stocks.csv`
   (if the account's value changed) and/or `logs/trade_log_crypto.csv`/
   `logs/trade_log_stocks.csv` (if it actually bought or sold
   something) - an uneventful run writes to neither. Crypto and stocks
   each write to their own pair of files (via `live_trade.py`'s
   `--log-suffix`), specifically so the two workflows never commit to
   the same file at nearly the same moment. Whenever a file does
   change, the workflow commits that update back to the repo, so
   `git pull` locally will show new commits with a "Log ... trading
   run" message over time. That's the automated bot committing its own
   log, not me.
   See "Logs and the trade dashboard" below for what's in each file.

**Important - avoid double-trading:** once GitHub Actions is confirmed
working, **turn off your local Windows Task Scheduler tasks** (or the
cron jobs, if you're on Mac/Linux). If both your PC and GitHub Actions
are scheduled to run at the same time against the same Alpaca account,
you'd get duplicate orders - each one independently deciding to buy,
unaware the other already did. Only one automation path should be active
against a given account at a time. To disable in Task Scheduler: find the
task, right-click -> Disable (or Delete, once you're confident GitHub
Actions is working reliably).

## Setting up cron-job.org (recommended - GitHub's own schedule trigger isn't reliable enough on its own)

GitHub Actions' `schedule:` trigger is real and does fire sometimes, but
it wasn't reliable enough on its own in my testing - runs would silently
not happen. Every workflow in this repo also accepts
`workflow_dispatch: {}`, which means it can be started by an API call on
demand - [cron-job.org](https://cron-job.org) (free) is what actually
calls that API on a schedule, working around GitHub's flaky one.

1. **Create a GitHub token that's allowed to trigger workflows.** Go to
   GitHub -> your avatar -> **Settings -> Developer settings -> Personal
   access tokens -> Fine-grained tokens -> Generate new token**. Scope it
   to **only this repository**, and under **Repository permissions** set
   **Actions: Read and write**. Nothing broader than that is needed -
   see "Security" in the main README for why scoping it this narrowly
   matters. Copy the token immediately; like an Alpaca key, it's only
   shown once.
2. **Sign up for a free account at [cron-job.org](https://cron-job.org).**
3. **Create a new cronjob** (repeat this whole step once per workflow you
   want automated - crypto, stocks, retrain, dashboard):
   - **Title:** anything recognizable, e.g. "InvestingBot - crypto"
   - **URL:**
     ```
     https://api.github.com/repos/<your-username>/InvestingBot/actions/workflows/paper-trade-crypto.yml/dispatches
     ```
     (swap the filename for `paper-trade-stocks.yml`, `retrain-stock-model.yml`,
     or `update-dashboard.yml` for the other three jobs)
   - **Request method:** `POST`
   - **Request headers:** add three:
     ```
     Accept: application/vnd.github+json
     Authorization: Bearer <your fine-grained token from step 1>
     X-GitHub-Api-Version: 2022-11-28
     ```
   - **Request body** (JSON), naming whichever branch this is running on:
     ```json
     {"ref": "claude/trading-bot-feasibility-31mkkv"}
     ```
   - **Schedule:** every 5 minutes for crypto; every 5 minutes during
     regular market hours (roughly 9:30am-4:00pm ET, weekdays) for
     stocks - the live stock strategy is a 5-minute-bar candidate, so it
     needs to be evaluated that often to behave the way it was
     walk-forward validated, not once a day; weekly for the retrain job;
     hourly for the dashboard.
4. **Save, then test it immediately** - cron-job.org lets you trigger a
   job manually rather than waiting for its schedule. Do that, then check
   the **Actions** tab on GitHub for a new run of that workflow. A `401`
   or `404` response usually means the token's scope or the URL/filename
   is wrong; double-check both.
5. **Repeat for the other three workflows.** Once all four are confirmed
   firing, this repo runs itself with zero computers of mine needing to
   stay on.

## Crypto support

`--ticker` also accepts crypto: just pass the base symbol (`BTC`, `ETH`,
`SOL`, `DOGE`, `LTC`, and others - see `KNOWN_CRYPTO_BASES` in
`src/symbols.py`). It's auto-detected and mapped to the right format for
both Yahoo Finance (`BTC-USD`) and Alpaca (`BTC/USD`) automatically.

**Live crypto trading pulls price data from Alpaca, not Yahoo Finance**
(`src/alpaca_data.py`) - Yahoo's intraday crypto bars can silently go
stale for hours without erroring (serving an old price as if it were
current), so `live_trade.py` uses Alpaca's own crypto market data
instead: the same venue trades actually execute against, and every
fetch gets checked against a staleness threshold - if the latest bar is
older than expected for the requested interval, that ticker gets skipped
for the run rather than traded on outdated data. Backtesting (`main.py`)
still uses Yahoo Finance for crypto, since staleness doesn't matter for
historical data - though for *walk-forward validation*
(`walk_forward.py`, `optimize.py`) crypto tickers now prefer Alpaca's
own historical bars instead, since Yahoo's ~60-day intraday cap turned
out to be the shorter of the two, not the longer one (see
`docs/RESEARCH.md`).

**Crypto trades 24/7**, unlike stocks, and the GitHub Actions crypto
workflow (`.github/workflows/paper-trade-crypto.yml`) is configured for
day trading rather than the once-a-day daily-close strategy:

```bash
python live_trade.py --ticker BTC ETH SOL DOGE LTC AVAX LINK XRP DOT \
  --strategy day_trading --interval 5m \
  --dip-threshold -0.04 --profit-target 0.01 --stop-loss 0.05 \
  --execute
```

This runs on 5-minute bars, buys a **4.0%+** dip, and sells once my
*actual* position is up 1.0% - or cuts it at **-5.0%** if the dip keeps
falling instead of bouncing. These thresholds changed on 2026-07-27 -
the prior 1.0%/1.0%/3.0% combo fired on any 1%+ dip, which happens
constantly on 5-minute bars, and a `walk_forward.py` run against a real
year of Alpaca data found it losing money in 53 of 54 ticker/window
tests. The 4% threshold only buys real, comparatively rare dips instead,
and the same real-data validation improved to 49 of 54 non-negative
results - see `CHANGELOG.md` 0.7.0 and `docs/RESEARCH.md` for the full
evidence (both the `optimize.py` grid search and the `walk_forward.py`
validation that found this combo are committed as
`results/param_sweep/param_sweep.csv` and `results/walk_forward/walk_forward.csv`, not just
described). I re-run that search periodically as more real trade history
accumulates, since "best on the data tested" isn't a permanent property.

**Thresholds should match real observed volatility, not be picked
arbitrarily.** The very first 2%/2%/4% thresholds never fired a single
trade in practice - actual short-term crypto moves during a live check
were closer to 0.05-0.2% over 5-minute windows, so a 2% dip essentially
never happens on that timeframe; the 1%/1%/3% combo that replaced it
turned out to fire *too* often instead, as the 2026-07-27 validation
above found. Before changing these numbers, check what the market is
actually doing - pull real price data (e.g. via `main.py`, `optimize.py`,
or `walk_forward.py`, all of which fetch it fresh) rather than guessing.
`trade_log.csv` itself only records actual BUY/SELL decisions now (see
"Logs and the trade dashboard" below), so it's no longer a dense price
history the way it briefly was.

**Worth knowing before you tighten these further:** more frequent
trading means more round trips, and every round trip pays Alpaca's
crypto spread/fee (roughly 0.15-0.25% each way, so ~0.3-0.5% per full
buy-sell cycle). If `--profit-target` is smaller than that fee drag, the
strategy loses money **on average even when directionally correct** -
there's a real floor below which "more trades" just means "more fee
payments," not more profit. The 1.0% target has stayed the same across
both threshold changes, deliberately above that floor; going much lower
trades against the fee structure, not with it. Real fills so far land
toward the higher end of that fee range - one closed trade paid about
0.25%, another about 0.44% - worth treating the floor as a range to stay
clear of, not a precise number to shave against. The 2026-07-27 change
(loosening the *dip threshold*, not the profit target) tackled the same
fee-drag problem from the other direction: trading far less often instead
of trying to out-earn the fee on every single trade.

**Backtest it before trusting a threshold change** - same principle as
the stock strategy, just with intraday data and crypto-realistic fees:
```bash
python main.py --ticker BTC-USD --interval 1h \
  --start 2026-05-01 --split 2026-07-01 --end 2026-07-25 \
  --cost-bps 20 --dip-threshold -0.04 --profit-target 0.01 --stop-loss 0.05
```
(Yahoo Finance only keeps a limited window of intraday history, so keep
`--start` recent rather than reaching back years like the daily stock
backtest does.)

If you'd rather run stocks and crypto with matching strategies/settings
instead, both workflows accept the same `--strategy`, `--interval`,
`--dip-threshold`, `--profit-target`, and `--stop-loss` flags - edit the
`run` line in either `.github/workflows/paper-trade-*.yml` file to
change what it does.

## Logs and the trade dashboard

Every `live_trade.py` run writes to two separate CSVs, both git-tracked so
`git pull` shows the bot's own history over time. Crypto and stocks each
write to their own pair of files (`--log-suffix _crypto` /
`--log-suffix _stocks`) rather than sharing one - two workflows
committing to the exact same file at nearly the same moment was a real,
reproduced source of failed pushes (see `CHANGELOG.md` 0.9.7/0.9.8), so
each asset class gets its own:

- **`logs/equity_log_crypto.csv` / `logs/equity_log_stocks.csv`** -
  `timestamp_utc`, `mode`, `portfolio_value_usd`, `cash_usd`, at most one
  row per run (not per ticker) - and only when the account value
  actually differs from the last logged row. Most runs change nothing
  (no trade, no open position whose price moved), so most runs write
  nothing here at all; a real change, even a small one, still gets
  logged immediately. This keeps each file a clean time series of "what
  was the account worth, and when did that change" without a row for
  every unchanged 5-minute check-in. Both files describe the same one
  account's total value (crypto and stocks share a single Alpaca paper
  account) - `visualize_log.py` reads both and merges them into one
  combined timeline for the whole-account panel; the split is only
  about which workflow happened to write a given sample, not two
  separate account balances.
- **`logs/trade_log_crypto.csv` / `logs/trade_log_stocks.csv`** - one row **per actual BUY/SELL decision**
  (dry-run or executed): `timestamp_utc`, `mode`, `asset_class`, `ticker`,
  `strategy`, `action`, `price_usd`, `notional_usd`,
  `position_qty_before`, `avg_entry_price_usd`, `unrealized_gain_pct`
  (already a percentage, e.g. `1.08` means +1.08%, not `0.0108`),
  `order_placed` (whether it was a live order vs. a dry run), and `notes`
  - a manual annotation slot, empty by default, never written by the bot
    itself. I use it to flag a specific trade as unrepresentative (e.g.
    "position was 2x intended size due to a since-fixed bug") without
    ever deleting or hiding the real result - `visualize_log.py` reads
    this to show both the honest full history and a "how is the
    strategy itself actually doing" view side by side, see below.
  **HOLD decisions aren't logged here** - see below for why.

**Why HOLD isn't logged, and whether the crypto log will get "too big"
eventually:** it would, if every 5-minute crypto run wrote a row per
ticker regardless of outcome - at 9 coins every 5 minutes that's ~2,600
rows/day, and since every workflow run also **commits** that file, it
would mean roughly 288 git commits a day forever just from crypto HOLDs.
That's real repo bloat (slow clones, unreadable history) for close to
zero information, since the vast majority of runs are HOLD and the console
output of that run (visible in the Actions tab for a while after) already
shows it happened. So `trade_log.csv` only gets a row when something
actually happened (a BUY or SELL signal fired), which cuts the volume by
roughly 100x based on this project's own history so far - and
`equity_log.csv` only writes a row when the value actually changed since
the last one, which cuts it further still, since a flat, untraded
account produces zero new rows run after run. Two prior rebuilds are
kept for reference, never deleted: `logs/trade_log_archive_pre_2026-07-25.csv`
(the very first log format, whose header didn't actually match its
data - the bug that motivated that rewrite) and
`logs/trade_log_archive_pre_2026-07-27.csv` (every trade from before
stock automation was paused and the live crypto thresholds changed to
the 0.7.0 values - see `CHANGELOG.md` 0.8.0. Both archived files still
work as `--trade-log` input to `visualize_log.py` if I ever want to look
back at what a prior model actually did).

**`python visualize_log.py`** turns both files into a five-panel PNG
(`results/trade_dashboard.png` by default): net account gain/loss (one
panel, the whole account, crypto and stocks combined - the single
authoritative "how much has this account actually made" figure, since
it's built from real account equity, not the trade log), then
cumulative realized P&L and win/loss-per-ticker, each split into two
side-by-side panels - one for crypto, one for stocks - rather than
blended into one. Crypto runs day_trading, stocks run ml_filtered/
rule_based - two strategies with nothing in common, so a shared P&L line
or a shared per-ticker bar chart would say less than two separate ones
do. A snapshot from before this split (and before stock automation was
paused), for comparison, is archived at
`results/trade_dashboard_archive_pre_2026-07-27.png`. I run
`visualize_log.py` locally anytime for an on-demand snapshot - harmless,
no network/broker access needed, just reads the two log files.

**The account-total panel and the two P&L panels answer different
questions and won't sum to the same number - that's expected, not a
bug.** The account-total panel is the authoritative "how much has this
account actually made" figure. The per-asset-class P&L panels only cover
trades present in the *current* `trade_log.csv` - since that file gets
rebuilt from scratch whenever the logging format or the live strategy
changes (see the archived-log notes above), they can't see anything
that happened before their own most recent rebuild, even though that
activity is still baked into the account equity the top panel reads.
Trust the top panel for the account total; use the P&L panels only for
"were the trades I can actually see here, in this asset class,
profitable."

**The account-total panel's baseline matters and is easy to misread.**
By default it's equity minus the *first* row across both equity logs -
i.e. "gain/loss since equity logging happened to start," which isn't the
same as "since I funded the account," especially if trades were already
open before logging began. Pass `--baseline 100000` (or whatever your
actual starting cash was) to measure from your real starting point
instead - the title changes to make clear which one you're looking at.
Both are valid, they just answer different questions - but showing only
the "since tracking began" one risks looking like it disagrees with what
Alpaca's own dashboard says, when both numbers are actually correct,
just measuring from different starting points. Use `--baseline` whenever
you want the number that matches Alpaca's own total account P&L.

It also runs on a schedule: `.github/workflows/update-dashboard.yml`
regenerates and commits `results/trade_dashboard.png` roughly hourly
(with `--baseline 100000`, via an external scheduler - GitHub's own
`schedule:` trigger isn't reliable enough on its own here either, same
as the trading workflows), so `results/trade_dashboard.png` on GitHub
stays close to current without me needing to run anything locally - just
open that file's page on github.com. This is deliberately a slower
cadence than the 5-minute trading workflows: one image commit an hour is
a small, bounded cost, where committing an image every 5 minutes forever
would not be.

## Stock automation: rule-based, 5-minute bars

**Currently paused** (see `CHANGELOG.md` and "Current live status" in
the main README). `paper-trade-stocks.yml` has **no `schedule:` trigger
of its own anymore** - only `workflow_dispatch: {}` - so GitHub itself
will never fire it; it only runs if a human clicks "Run workflow" or an
external scheduler (cron-job.org) calls its dispatch endpoint on
purpose. That's a deliberate, structural change, not just a documentation
note: an earlier version of this workflow kept a native `schedule:`
trigger active even after the README/CHANGELOG declared stocks
"paused," which - combined with a stale, never-validated `ml_filtered
--dip-threshold -0.03` command left over from before this project's
walk-forward work - caused an unwanted live BUY. "Paused" now means the
workflow structurally cannot run on its own, not just that the docs say
it shouldn't.

The live strategy is `rule_based`, 5-minute bars, `dip=-1.5% /
exit=2.0%` - the best-of-8 candidate that actually came out ahead in
walk-forward validation (see `docs/RESEARCH.md`), not `ml_filtered`.
Because it's sized for 5-minute bars, it needs to be evaluated about
every 5 minutes during market hours to behave the way it was tested -
running it once a day would not reproduce the validated behavior at
all (see "Setting up cron-job.org" above).

`ml_filtered` is still a real option in `live_trade.py`/`optimize.py`/
`walk_forward.py` for anyone who wants to keep researching it - it just
isn't what's wired into the live workflow anymore, since walk-forward
testing found it wasn't the strongest candidate. Its supporting
retraining pipeline still exists if you want it:
`live_trade.py --strategy ml_filtered` loads whatever model is saved at
`--model-path` (default `models/stock_model.pkl`) rather than training
one on the spot. That file is produced by a **separate** workflow,
`.github/workflows/retrain-stock-model.yml`, which runs
`train_stock_model.py` - it pools recent data from **9 tickers spanning
several sectors on purpose** (SPY/QQQ broad market, AAPL tech, JPM
financials, XOM energy, JNJ healthcare, KO consumer staples, CAT
industrials, DIS media/consumer discretionary) into one model. A
setting (or a model) that only works on one sector isn't a real edge,
same principle as `optimize.py`'s cross-ticker averaging - and it
directly addresses the correlation problem the crypto side ran into,
where several coins moving together in the same market swing inflated
how independent the "evidence" actually was. Commits the result back to
the repo, which is what makes the live stock model "learn" in the sense
of updating over time, instead of being fixed at the moment I wrote this
code:

```bash
python train_stock_model.py --ticker SPY AAPL QQQ JPM XOM JNJ KO CAT DIS --lookback-days 730
```

**Setup, in order, for the live `rule_based` strategy:**
1. Complete the GitHub Actions setup above (secrets, write permissions)
   if you haven't already.
2. Point cron-job.org (or any external scheduler) at
   `paper-trade-stocks.yml`'s `workflow_dispatch` endpoint, the same way
   it's already wired up for crypto - see "Setting up cron-job.org"
   above. A reasonable cadence: every 5 minutes during regular market
   hours (roughly 9:30am-4:00pm ET, weekdays) - matching the bar size
   the live strategy was actually validated at, not once a day.
3. (Optional, only if you also want `ml_filtered` available for
   research) Go to the **Actions** tab -> **"Retrain stock ML model"**
   -> **"Run workflow"** once, manually, to produce the first
   `models/stock_model.pkl`. Until this has run at least once,
   `live_trade.py --strategy ml_filtered` falls back to training inline
   from just that run's data (it prints a warning when this happens)
   rather than failing outright. A reasonable cadence if you automate
   it: weekly.

Every retrain also appends a row to `logs/retrain_log.csv` (tickers
used, training window, row count, calibrated threshold) so I can see
the model's history over time, the same way the trade logs track trade
history.
