<div align="center">

# InvestingBot — Version Richards 0.9.7

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Tests: 79 passing](https://img.shields.io/badge/tests-79%20passing-4c9a2a)](tests/)
[![Mode: paper trading only](https://img.shields.io/badge/mode-paper%20trading%20only-orange)](docs/RISK.md)
[![Demonstrated edge: not yet](https://img.shields.io/badge/demonstrated%20edge-not%20yet-lightgrey)](CHANGELOG.md)

*A systematic "buy the dip" strategy for stocks and crypto — backtested, searched, validated, and paper-traded in the open.*

</div>

Version history lives in `CHANGELOG.md`.

A "buy the dip" stock and crypto strategy: I backtest it, search for better
settings systematically, then optionally run it automatically against a
paper (fake-money) brokerage account.

> [!WARNING]
> **Not investment advice.** I built this to answer a specific question before
> any real money gets involved: do these dip-buying rules actually beat just
> buying and holding? For a long time the honest answer was no. As of
> 2026-07-27, walk-forward validation against a real year of data found a
> configuration that may have found something real - **meaningfully
> de-risked, not yet a proven steady edge** - which is exactly why it's
> running live on the paper account now instead of just sitting in a
> backtest. See "Current live status" below for the full picture, caveats
> included. I'm only going to consider real money once
> something actually demonstrates an edge with real trades, not just
> backtested ones.

## Contents

- [Documentation](#documentation)
- [Current live status](#current-live-status-as-of-this-writing)
- [Setup](#setup)
- [Architecture](#architecture)
- [Security: who can see what, and who can change what](#security-who-can-see-what-and-who-can-change-what)
- [Disclaimer](#disclaimer)

---

## Documentation

This README covers the overview, current status, installation, and
architecture. Deeper material lives in `docs/`:

- **[docs/BEGINNER_GUIDE.md](docs/BEGINNER_GUIDE.md)** - new to this
  project, or newer to coding in general? A plain-English walkthrough of
  every piece: what a workflow file is, what `--strategy day_trading`-style
  options mean, why this is all in Python, how the automation runs every
  5 minutes without a computer being on, plus a glossary of terms used
  throughout this repo.
- **[docs/AUTOMATION.md](docs/AUTOMATION.md)** - setting up automated
  paper trading: Alpaca account/keys, GitHub Actions, cron-job.org, crypto
  vs. stock specifics, and how logging/the trade dashboard work.
- **[docs/RISK.md](docs/RISK.md)** - the risk controls currently in
  place (circuit breaker, position cap), and what's required before this
  ever touches real money.
- **[docs/RESEARCH.md](docs/RESEARCH.md)** - backtesting, what each
  strategy and the ML model actually do, and the two tools for searching
  and validating parameter choices (`optimize.py`, `walk_forward.py`).
- **[CHANGELOG.md](CHANGELOG.md)** - full version-by-version history.

---

## Current live status (as of this writing)

I keep this section updated so I don't have to reverse engineer what's
actually running from workflow files six months from now. This is a
snapshot and will be stale by the time you read it - check
`results/trade_dashboard.png` for the live number.

**Crypto and stocks run completely independently** - different tickers,
different strategy code, different thresholds, separate on/off
switches. The table below puts them side by side specifically so
neither one is a mystery relative to the other:

| | Crypto | Stocks |
|---|---|---|
| **Automation** | Running (paper), every 5 min | **Paused** (2026-07-28 incident - see below) |
| **Auto-trigger** | GitHub's own `schedule:` (every 5 min) | **None** - `paper-trade-stocks.yml` only runs on a manual click or an external call, never on its own |
| **Strategy** | `day_trading` (rule-based, no ML) | `rule_based` (rule-based, no ML) - wired in, not yet running |
| **Tickers** | BTC, ETH, SOL, DOGE, LTC, AVAX, LINK, XRP, DOT | SPY, AAPL, QQQ, JPM, XOM, JNJ, KO, CAT, DIS |
| **Bar size** | 5-minute | 5-minute |
| **Buy signal** | price ≥4.0% below its 20-bar average | price ≥1.5% below its 20-bar average |
| **Sell signal** | +1.0% profit **or** -5.0% stop-loss from entry | back within 2.0% of the average (no stop-loss) |
| **Max $ per trade** (`--max-notional`) | $2,000 | $2,000 |
| **Daily loss circuit breaker** | 5% of that day's starting balance | 5% of that day's starting balance |
| **Demonstrated edge?** | No - "meaningfully de-risked," not proven | No - best-of-8 walk-forward candidate, not proven |
| **Closed trades (current config)** | Accumulating - see dashboard | 0 closed - 3 open positions (XOM, CAT, DIS) from 2026-07-28 manual testing, archived trades from 2 prior incidents, see below |

Both share: **real-money mode disabled** (2 independent locks - see
`docs/RISK.md`), and **stock model retraining off on purpose**
(`retrain-stock-model.yml` has no auto-trigger either - `ml_filtered`
isn't live right now, so there's nothing to retrain for).

**What "79 tests passing" (`pytest tests/`) actually means:** these are
fast, offline checks that specific pieces of code do what they're
supposed to on made-up numbers - e.g. "does the stop-loss actually
trigger when price falls exactly 5% below entry," "does the circuit
breaker actually block a new BUY once the account is down 5% today,"
"does `has_open_order()` actually stop a second order from stacking on
an unfilled one." **They say nothing about whether either strategy
makes money** - that question is only ever answered by the backtests,
grid searches, and walk-forward validation described below, run
against real market data, never by the test suite. A green test suite
means the code isn't broken; it does not mean the strategy is good. CI
(`.github/workflows/ci.yml`) runs this same suite automatically on
every push/PR, so a broken change can't reach this branch unnoticed.

- **Crypto: rule-based, no ML. Thresholds changed 2026-07-27, backed by
  real validation evidence.** An external free scheduler
  ([cron-job.org](https://cron-job.org)) calls GitHub's API every 5
  minutes to run `.github/workflows/paper-trade-crypto.yml`, which runs
  `live_trade.py --strategy day_trading` against **BTC, ETH, SOL, DOGE,
  LTC, AVAX, LINK, XRP, DOT** on 5-minute bars: buy a **4.0%** dip, sell
  at **+1.0%** profit or **-5.0%** stop-loss (previously 1.0% / 1.0% /
  3.0%). The old combo bought on any 1%+ dip, which fires constantly on
  5-minute bars; a `walk_forward.py` run against a real year of Alpaca
  data found it losing money in 53 of 54 ticker/window tests, with
  100-1,000+ trades per ticker in a single ~2-month window - transaction
  costs alone likely explain a large share of that. The new -4%
  threshold only buys real, comparatively rare dips (4-52 trades per
  ticker over the same full year) and improved to 49 of 54 non-negative
  results. **Real evidence, committed and checkable:**
  [`results/param_sweep.csv`](results/param_sweep.csv) (the 90-combo
  grid search that found this combo) and
  [`results/walk_forward.csv`](results/walk_forward.csv) (its per-window
  validation). Read this as **meaningfully de-risked, not yet a proven
  steady edge** - a large share of the gain sits in two specific
  calendar windows where several coins moved together (more likely a
  broad market swing than nine independent edges), and a couple of the
  winning windows had large intra-window drawdowns (LTC -37.7%, LINK
  -31.8%) that their final positive return doesn't show. Now
  accumulating fresh real trade history under the new settings - see
  `CHANGELOG.md` 0.7.0 for the full writeup.

  <img src="results/param_sweep_overview.png" alt="Scatter plot of the 90-combination grid search: average trades per ticker on the x-axis, average return on the y-axis, colored by dip threshold. Return climbs sharply as trade count drops, and the chosen combo (circled) sits at the top-left with the fewest trades and the best return." width="720">

  <img src="results/walk_forward_winner.png" alt="Nine small-multiple bar charts, one per coin, showing the chosen combo's return in each of 6 sequential real-data windows from August 2025 to July 2026. Most windows are small positive or flat bars; a handful are large positive spikes concentrated in the same two calendar windows across several coins; a few are small red losses." width="720">

- **Stocks: paused as of 2026-07-27.** The account was carrying an
  unmanaged ~$33k QQQ position (about a third of its value) from an
  order that silently filled sometime after being submitted outside
  market hours - never logged, since `live_trade.py` only records a
  trade at the moment a run makes a fresh decision, not when an old
  pending order quietly clears later on its own. That discovery also
  surfaced a real gap: unlike crypto, the stock workflow never had
  `--max-notional` or `--daily-loss-limit` wired in at all - nothing was
  capping how large a single stock position could grow. The cron-job.org
  jobs driving `paper-trade-stocks.yml`/`retrain-stock-model.yml` are
  paused and the QQQ position was closed manually; see `CHANGELOG.md`
  0.8.0. `optimize.py`/`walk_forward.py` now both support `--strategy
  rule_based` (see `docs/RESEARCH.md`) so the stock strategy can
  actually be validated, the same way crypto's was, before stocks ever
  resume. The ticker list also grew from 3 to 9 while paused - SPY/QQQ
  (broad market), AAPL (tech), JPM (financials), XOM (energy), JNJ
  (healthcare), KO (staples), CAT (industrials), DIS (media) - spanning
  several sectors on purpose, the same "one ticker isn't a real edge"
  principle crypto's validation already leans on.
- **Stock validation: 8 candidates walk-forward tested. Best of the 8:
  `rule_based`, 5-minute bars, dip=-1.5% / exit=2.0%.** Across an
  extensive search - daily and 5-minute bars, the plain `rule_based`
  rule, a version with a hard stop-loss and re-entry cooldown added, and
  `ml_filtered` (the same rule gated by a trained ML model) - this one
  candidate stood out clearly: its walk-forward loss rate (**17.5%** of
  ticker-windows) is well below every other candidate's (which cluster
  25-32%), while its average return (3.06%/ticker) is still solidly
  mid-pack, not a trade-off against the best. **Why it's the best of the
  8, not just the highest number:** every other candidate that scored
  well on one axis (return, or trade count) scored poorly on another
  (consistency, or sample size) - this is the only one that didn't trade
  that strength away. See it circled in the charts below and compared
  directly against all 7 others in the summary chart. **Still not a
  proven edge** - one year of 5-minute data is a much shorter validation
  window than crypto's, and 8.6 average trades per ticker is a real but
  thin sample. Read it as "the strongest lead of what's been tried,"
  not "ready to deploy." Stocks stay paused either way (see below) until
  a candidate clears a materially higher bar than this.
  `get_stock_bars_range()` (`src/alpaca_data.py`) lets stocks pull
  intraday bars from Alpaca now, the same way crypto does;
  `rule_based_dip_buy()` gained an optional `stop_loss` +
  `stop_cooldown_bars` (a real walk-forward run found the stop-loss
  alone could backfire - SPY's 2019-2021 window went from -3.2% to
  -27.4% - fixed by adding the cooldown); `optimize.py`/`walk_forward.py`/
  `train_stock_model.py` all gained `--strategy ml_filtered` support.
  Every grid and walk-forward run is committed as real evidence in
  `results/` (see `docs/RESEARCH.md` for the full candidate-by-candidate
  breakdown and every command used).

  <img src="results/walk_forward_stocks_summary.png" alt="Two side-by-side bar charts comparing all 8 walk-forward-tested stock candidates: average return per ticker on the left, percent of losing ticker-windows on the right, colored by strategy variant (plain rule, rule plus stop-loss, ML-filtered). The 5-minute dip=-1.5%/exit=2.0% candidate is outlined in black and marked with a star, with an annotation pointing out its clearly lower loss rate (about 17.5%) compared to every other candidate (25-32%), while its return sits mid-pack." width="720">

  <img src="results/walk_forward_stocks_5m_best_candidate.png" alt="Nine small bar charts, one per ticker (SPY, AAPL, QQQ, JPM, XOM, JNJ, KO, CAT, DIS), each showing that ticker's return across the same 7 sequential walk-forward windows for the winning candidate (5-minute bars, dip=-1.5%/exit=2.0%). Most tickers show mostly green (positive) windows with only one or two red (negative) ones; SPY and KO show several gray (no-trade) windows; DIS is the clear outlier with 4 of 7 windows negative." width="720">

  <img src="results/param_sweep_overview_stocks_daily_all.png" alt="Scatter plot combining three daily grid searches (plain rule-based, rule-based with stop-loss and cooldown, and ML-filtered), average trades per ticker on the x-axis, average return on the y-axis. The ML-filtered points (triangles) sit in a visibly lower return band than the plain-rule points (circles and squares), which cluster together around 20-25 percent. A note box explains that the overall best-of-8 candidate actually came from the 5-minute search shown in the next chart, not from this daily one." width="720">

  <img src="results/param_sweep_overview_stocks_5m_all.png" alt="Scatter plot combining three 5-minute grid searches (plain rule-based, rule-based with stop-loss and cooldown, and ML-filtered). All three variants' points are intermixed in a loose cloud between roughly 0 and 7 percent return. One point - dip=-1.5% exit=2.0%, plain rule-based - is circled and labeled as the best walk-forward result of all 8 candidates tested." width="720">
- **Second stock incident, 2026-07-28: "paused" wasn't actually
  enforced anywhere.** Confirmed via the GitHub Actions API: the run
  that placed these trades has `event: "schedule"` at
  `2026-07-27T23:41:42Z` - `.github/workflows/paper-trade-stocks.yml`
  still had its own native GitHub `schedule:` trigger (cron `55 19 * *
  1-5`, i.e. ~19:55 UTC), which fired regardless of the README/CHANGELOG
  saying stocks were paused, and this time nearly 4 hours late (a known
  failure mode for GitHub's schedule trigger already documented in this
  repo - previously seen as "silently doesn't fire," this time as
  "fires very late instead"). Separately, the Actions history also shows
  `workflow_dispatch` runs at ~19:55 UTC on 2026-07-25 and 2026-07-26
  (no trades logged those days) - meaning the cron-job.org job for this
  workflow had *also* remained active the whole time, independent of the
  native schedule bug, contrary to the "paused" documentation. Both were
  still running a stale `ml_filtered --dip-threshold -0.03` command left
  over from before the walk-forward work above, not the validated
  best-of-8 candidate. That combination bought **3 tickers - QQQ, CAT,
  and DIS, ~$11,087 each** (confirmed from the archived
  `logs/trade_log_archive_pre_2026-07-28.csv`) - on real (paper) money
  the account owner never intended to be trading.
  **Fixed structurally, not just in documentation:** the workflow's
  `schedule:` trigger has been removed entirely - only
  `workflow_dispatch: {}` remains, so GitHub itself can never fire it
  again; the only way it runs is a deliberate manual click or an
  external scheduler (cron-job.org) call. `retrain-stock-model.yml`'s
  native schedule was removed too, on the same reasoning, since
  `ml_filtered` isn't the live strategy right now. The committed
  strategy args were also corrected to the actual best-of-8 candidate
  (`rule_based`, `--interval 5m`, `--dip-threshold -0.015
  --exit-threshold 0.02`) with `--max-notional 2000
  --daily-loss-limit 0.05` added - stocks were missing those caps
  entirely before (each of the 3 buys above spent an uncapped 1/9th of
  total cash), the same gap the first (QQQ) incident above already
  found on the daily config. Stocks remain paused: the account owner
  has now paused the cron-job.org job for this workflow too, so nothing
  calls it until a human deliberately re-enables it. The tainted trade
  log was archived to `logs/trade_log_archive_pre_2026-07-28.csv` and
  `logs/trade_log.csv` restarted fresh (`logs/equity_log.csv`
  deliberately not archived - account equity is a continuous truth,
  same reasoning as the first incident's archival).
- **Post-incident hardening, 2026-07-28.** Also fixed while addressing
  the incident above, from an independent technical review: `main.py`/
  `optimize.py`/`walk_forward.py` previously scaled annualized
  return/volatility/Sharpe for ANY intraday interval using a 24/7
  bars-per-year count (correct for crypto, wrong for stocks - US
  equities trade ~6.5 regular hours/day, not around the clock). Total
  return and drawdown were never affected, only the annualized figures -
  the 8-candidate comparison above was based on total return, so it's
  unaffected by this. Added `src/data.py`'s `periods_per_year()`,
  asset-class-aware, used consistently now. Also added: a CI workflow
  (`.github/workflows/ci.yml`) running the test suite on every push/PR,
  since none existed before; all 5 workflows' `actions/checkout`/
  `actions/setup-python` pinned to full commit SHAs instead of movable
  version tags; and a SHA256 integrity check on the saved ML model file
  in `src/model_store.py` - `joblib.load()` can execute arbitrary code
  for a tampered file, and this one is written by automation and trusted
  by live code later, so `load_model()` now refuses to load a file whose
  hash doesn't match what was recorded when it was last saved.
- **Dashboard: five panels, regenerated hourly.** `results/trade_dashboard.png`
  is committed automatically, viewable directly on github.com: one
  whole-account net gain/loss panel, plus cumulative realized P&L and
  win/loss-per-ticker each split into separate crypto/stock panels
  rather than blended together - two very different strategies sharing
  one chart said less than two side by side do. A snapshot from before
  this split and before the pause above is archived at
  `results/trade_dashboard_archive_pre_2026-07-27.png`.
- **Current results snapshot:** the account is at **-$212.90** against
  its $100,000 funding baseline - includes the just-closed QQQ position's
  realized loss, on top of the +$292.84 the account was at from crypto
  trading before that close. `logs/trade_log.csv` was archived to
  `logs/trade_log_archive_pre_2026-07-27.csv` alongside the threshold
  change (its 3 old-model crypto trades: realized P&L **-$533.58** all
  together, or **+$365.37** excluding the one flagged bug-inflated
  trade) and started fresh, so it currently has zero rows - the new
  crypto config hasn't closed a trade yet. Full history of every bug and
  change that shaped these numbers is in `CHANGELOG.md`.

---

## Setup

Everything below takes you from a completely fresh machine (nothing
installed) to being able to run every command in this README. Pick
whichever section matches your operating system - both end up in the
exact same place.

**Prerequisites, either way:**
- Python 3.12 or newer
- git
- A free [Alpaca](https://alpaca.markets) account - only needed for
  live paper trading later on, not for the backtesting steps below

### Windows

1. **Install Python.** Download the installer from
   [python.org/downloads](https://www.python.org/downloads/). On the
   first install screen, check **"Add python.exe to PATH"** before
   clicking Install - easy to miss, and without it `python` won't be
   recognized in a terminal.
2. **Install git.** Download from
   [git-scm.com/download/win](https://git-scm.com/download/win) and run
   the installer, default options are fine.
3. **Open a terminal.** PowerShell works (search "PowerShell" in the
   Start menu).
4. **Clone the repository:**
   ```powershell
   git clone https://github.com/HarringtonEthan/InvestingBot.git
   cd InvestingBot
   ```
5. **Create and activate a virtual environment** - keeps this project's
   Python packages separate from anything else on your machine:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```
   The prompt should now start with `(venv)` - that confirms it worked.
6. **Install dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
7. **Verify it works:**
   ```powershell
   python main.py --ticker SPY --start 2015-01-01 --split 2022-01-01 --end 2024-12-31
   ```
   This should print a strategy comparison table and save a chart to
   `results/equity_curve.png`.

### macOS

1. **Install Python.** macOS ships with an old system Python that
   shouldn't be used for this - install a current version instead.
   Easiest path is [Homebrew](https://brew.sh):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   brew install python@3.12
   ```
   Or download the installer directly from
   [python.org/downloads](https://www.python.org/downloads/).
2. **Install git.** Usually already present - check with
   `git --version` in Terminal. If it's missing, macOS will prompt to
   install the Xcode Command Line Tools, or install it via Homebrew:
   `brew install git`.
3. **Open Terminal** (Applications -> Utilities -> Terminal, or
   Spotlight search "Terminal").
4. **Clone the repository:**
   ```bash
   git clone https://github.com/HarringtonEthan/InvestingBot.git
   cd InvestingBot
   ```
5. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
   The prompt should now start with `(venv)` - that confirms it worked.
6. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
7. **Verify it works:**
   ```bash
   python main.py --ticker SPY --start 2015-01-01 --split 2022-01-01 --end 2024-12-31
   ```
   This should print a strategy comparison table and save a chart to
   `results/equity_curve.png`.

Once setup is done, see `docs/AUTOMATION.md` to connect a real (paper)
Alpaca account and run this on a schedule, or `docs/RESEARCH.md` to run
and interpret a backtest first.

---

## Architecture

```
InvestingBot/
├── .env.example                  # Template for local Alpaca credentials - copy to .env, never commit .env itself
├── requirements.txt              # Pinned third-party Python dependencies
├── main.py                       # Backtest entry point (research only, no real broker involved)
├── optimize.py                   # Multi-ticker parameter sweep for the day-trading strategy
├── walk_forward.py               # Validates a parameter combo across multiple time periods, not just one
├── train_stock_model.py          # Trains and saves the stock ML dip-filter model
├── live_trade.py                 # Automated live (paper) trading entry point
├── visualize_log.py              # Builds the trade dashboard PNG from the logs below
├── src/
│   ├── data.py                   # Price data loading (Yahoo Finance + synthetic fallback; Alpaca-first for crypto validation)
│   ├── alpaca_data.py            # Live crypto price data (Alpaca, used instead of Yahoo)
│   ├── features.py               # Technical indicators (SMA, RSI, volatility, drawdown)
│   ├── strategies.py             # The five trading strategies
│   ├── model.py                  # ML dip-filter: training and label logic
│   ├── model_store.py            # Save/load a trained model to disk
│   ├── backtest.py               # Backtest engine: turns a position series into results
│   ├── broker.py                 # Alpaca account/order wrapper
│   └── symbols.py                # Resolves a ticker into Yahoo/Alpaca symbol formats
├── .github/workflows/
│   ├── paper-trade-crypto.yml    # Runs live_trade.py for crypto every 5 minutes
│   ├── paper-trade-stocks.yml    # Runs live_trade.py for stocks every ~5min in market hours (workflow_dispatch only - no GitHub-side schedule)
│   ├── retrain-stock-model.yml   # Runs train_stock_model.py weekly
│   └── update-dashboard.yml      # Runs visualize_log.py hourly
├── tests/                        # pytest suite - run with `pytest tests/`
├── docs/                         # Beginner guide, automation setup, risk controls, research tools
├── logs/                         # Generated: trade_log.csv, equity_log.csv, retrain_log.csv
├── models/                       # Generated: the saved stock_model.pkl and its metadata
├── results/                      # Generated: equity_curve.png, trade_dashboard.png, param_sweep.csv, walk_forward.csv, and their chart renders
├── CHANGELOG.md                  # Full version history
└── README.md                     # This file
```

**Two separate pipelines share code:**
- **Backtesting (research, no real money, no live prices):**
  `main.py` / `optimize.py` / `walk_forward.py` → `src/data.py` (fetch
  *historical* data) → `src/features.py` (compute indicators like
  RSI/SMA) → `src/strategies.py` (simulate what a strategy *would have*
  done) → `src/backtest.py` (score it: return, Sharpe, drawdown). Nothing
  here ever touches a real broker.
- **Live trading (paper money, real live prices, right now):**
  `live_trade.py` → `src/alpaca_data.py` or `src/data.py` (fetch
  *current* data) → `src/features.py` (same indicator code) →
  `src/strategies.py` or `src/model.py` (make today's actual decision)
  → `src/broker.py` (place the real - paper - order via Alpaca) →
  `logs/*.csv` (record what happened).

Both pipelines reuse the same feature/strategy code on purpose - it's
the only way to trust that a backtest result says anything about what the
live version will actually do; if they used separate logic, a good
backtest wouldn't mean anything about live behavior.

See `docs/RESEARCH.md` for what each strategy and the ML model actually
do, and `docs/AUTOMATION.md` for the live-trading, logging, and dashboard
files.

---

## Security: who can see what, and who can change what

A public GitHub repository means the source code is visible to anyone -
every strategy, every threshold, every workflow file. That doesn't mean
credentials are exposed; a few separate mechanisms decide what actually
is and isn't visible or changeable:

- **API keys and secrets are never in the code, and aren't visible to
  anyone once saved.** They belong in **GitHub Actions secrets**
  (Settings -> Secrets and variables -> Actions), a separate, encrypted
  vault from the repository itself. A secret's value can never be viewed
  again after saving - not by other people, not by me, only *used* by a
  workflow at runtime. If a workflow's console output ever tried to
  print one, GitHub automatically detects and masks it as `***` before
  the log is shown, public repo or not. This is why `ALPACA_API_KEY` /
  `ALPACA_SECRET_KEY` live there rather than in `.env` (which is
  git-ignored precisely so it's never committed by accident either).
- **Tokens used by an external scheduler (e.g. cron-job.org) live
  entirely outside this repository** - in that service's own account
  configuration, invisible to anyone browsing GitHub. Such a token is
  still a real, live credential: anyone who obtained it could trigger
  the linked workflows on demand. Scoping it as narrowly as possible -
  e.g. "Actions: read and write" on only this one repository, nothing
  else - limits the damage a leaked token could do to spam-triggering
  workflow runs, not pushing code or reaching a broker account directly.
- **Only explicitly added collaborators can push or edit code.** Check
  Settings -> Collaborators and teams on GitHub to see exactly who
  currently has write access - by default, that's just me, the
  repository owner. Being public means anyone can fork the repo and open
  a pull request proposing a change, but a pull request is only a
  proposal sitting in a queue: nothing merges into the repository unless
  someone with write access reviews and approves it.
- **Making a repository private** (Settings -> General -> Danger Zone ->
  Change visibility) hides the source code from public view entirely.
  It's purely a visibility toggle - it doesn't touch secrets or
  workflows, and the automation described throughout this project keeps
  working identically either way.

---

## Disclaimer

> [!NOTE]
> This project is for education and research. Nothing here is financial
> advice, and past backtest performance - synthetic or real - doesn't
> predict future results. I built this to learn, not to manage anyone's
> money, including my own, until it earns that.
