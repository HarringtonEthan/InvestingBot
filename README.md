<div align="center">

# InvestingBot — Version Richards 0.9.11

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Tests: 81 passing](https://img.shields.io/badge/tests-81%20passing-4c9a2a)](tests/)
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
`results/trade_dashboard.png` for the live number. **This section only
covers what's true right now** - every bug, incident, and past decision
that shaped this configuration is in `CHANGELOG.md`, not repeated here.

**Both crypto and stocks are currently RUNNING** (paper), triggered
**only** by an external scheduler ([cron-job.org](https://cron-job.org))
calling GitHub's `workflow_dispatch` API every 5 minutes for each.
Neither workflow has a GitHub-side `schedule:` trigger - GitHub itself
never fires either one on its own.

Crypto and stocks are otherwise completely independent - different
tickers, different strategy code, different thresholds, separate
on/off switches (each is its own cron-job.org job, so either can be
paused without touching the other). Same fields, side by side, so
neither one is missing information the other has:

| | Crypto | Stocks |
|---|---|---|
| **Running right now?** | Yes | Yes |
| **Triggered by** | cron-job.org only, every 5 min | cron-job.org only, every 5 min |
| **Strategy** | `day_trading` (rule-based, no ML) | `rule_based` (rule-based, no ML) |
| **Tickers** | BTC, ETH, SOL, DOGE, LTC, AVAX, LINK, XRP, DOT | SPY, AAPL, QQQ, JPM, XOM, JNJ, KO, CAT, DIS |
| **Bar size** | 5-minute | 5-minute |
| **Buy signal** | price ≥4.0% below its 20-bar average | price ≥1.5% below its 20-bar average |
| **Sell signal** | +1.0% profit **or** -5.0% stop-loss from entry | back within 2.0% of the average (no stop-loss) |
| **Max $ per trade** (`--max-notional`) | $2,000 | $2,000 |
| **Daily loss circuit breaker** | 5% of that day's starting balance | 5% of that day's starting balance |
| **Demonstrated edge?** | No - "meaningfully de-risked," not proven | No - best-of-8 walk-forward candidate, not proven |
| **Current positions/trades** | See `results/trade_dashboard.png` | See `results/trade_dashboard.png` |

Both share: **real-money mode disabled** (2 independent locks - see
`docs/RISK.md`), **stock model retraining off** (`ml_filtered` isn't
live right now, so there's nothing to retrain for), and **CI running
the test suite on every push/PR** (`.github/workflows/ci.yml`).

**What "81 tests passing" (`pytest tests/`) actually means:** these are
fast, offline checks that specific pieces of code do what they're
supposed to on made-up numbers - e.g. "does the stop-loss actually
trigger when price falls exactly 5% below entry," "does the circuit
breaker actually block a new BUY once the account is down 5% today,"
"does `has_open_order()` actually stop a second order from stacking on
an unfilled one." **They say nothing about whether either strategy
makes money** - that question is only ever answered by the backtests,
grid searches, and walk-forward validation linked below, run against
real market data, never by the test suite. A green test suite means
the code isn't broken; it does not mean the strategy is good.

- **Crypto: rule-based, no ML - buy a 4.0% dip, sell at +1.0% profit or
  -5.0% stop-loss.** Backed by a 90-combo grid search and walk-forward
  validation across a real year of Alpaca data. **Read as meaningfully
  de-risked, not yet a proven steady edge** - a large share of the gain
  sits in two specific calendar windows where several coins moved
  together (more likely a broad market swing than nine independent
  edges). **Real evidence, committed and checkable:**
  [`results/param_sweep/param_sweep.csv`](results/param_sweep/param_sweep.csv) (the grid search)
  and [`results/walk_forward/walk_forward.csv`](results/walk_forward/walk_forward.csv) (its
  per-window validation). Full writeup: `CHANGELOG.md` 0.7.0.

  <img src="results/param_sweep/param_sweep_overview.png" alt="Scatter plot of the 90-combination grid search: average trades per ticker on the x-axis, average return on the y-axis, colored by dip threshold. Return climbs sharply as trade count drops, and the chosen combo (circled) sits at the top-left with the fewest trades and the best return." width="720">

  <img src="results/walk_forward/walk_forward_winner.png" alt="Nine small-multiple bar charts, one per coin, showing the chosen combo's return in each of 6 sequential real-data windows from August 2025 to July 2026. Most windows are small positive or flat bars; a handful are large positive spikes concentrated in the same two calendar windows across several coins; a few are small red losses." width="720">

- **Stocks: `rule_based`, 5-minute bars, dip=-1.5% / exit=2.0% - the
  best of 8 candidates walk-forward tested.** Its loss rate (**17.5%**
  of ticker-windows) is well below every other candidate's (25-32%),
  while its average return (3.06%/ticker) is still solidly mid-pack -
  the only candidate that didn't trade one strength away for the
  other. **Still not a proven edge** - one year of 5-minute data, and
  8.6 average trades per ticker is a real but thin sample. Read it as
  "the strongest lead of what's been tried," not "ready to deploy."
  **Full candidate-by-candidate breakdown, every command used:**
  `docs/RESEARCH.md`.

  <img src="results/walk_forward/walk_forward_stocks_summary.png" alt="Two side-by-side bar charts comparing all 8 walk-forward-tested stock candidates: average return per ticker on the left, percent of losing ticker-windows on the right, colored by strategy variant (plain rule, rule plus stop-loss, ML-filtered). The 5-minute dip=-1.5%/exit=2.0% candidate is outlined in black and marked with a star, with an annotation pointing out its clearly lower loss rate (about 17.5%) compared to every other candidate (25-32%), while its return sits mid-pack." width="720">

  <img src="results/walk_forward/walk_forward_stocks_5m_best_candidate.png" alt="Nine small bar charts, one per ticker (SPY, AAPL, QQQ, JPM, XOM, JNJ, KO, CAT, DIS), each showing that ticker's return across the same 7 sequential walk-forward windows for the winning candidate (5-minute bars, dip=-1.5%/exit=2.0%). Most tickers show mostly green (positive) windows with only one or two red (negative) ones; SPY and KO show several gray (no-trade) windows; DIS is the clear outlier with 4 of 7 windows negative." width="720">

  <img src="results/param_sweep/param_sweep_overview_stocks_daily_all.png" alt="Scatter plot combining three daily grid searches (plain rule-based, rule-based with stop-loss and cooldown, and ML-filtered), average trades per ticker on the x-axis, average return on the y-axis. The ML-filtered points (triangles) sit in a visibly lower return band than the plain-rule points (circles and squares), which cluster together around 20-25 percent. A note box explains that the overall best-of-8 candidate actually came from the 5-minute search shown in the next chart, not from this daily one." width="720">

  <img src="results/param_sweep/param_sweep_overview_stocks_5m_all.png" alt="Scatter plot combining three 5-minute grid searches (plain rule-based, rule-based with stop-loss and cooldown, and ML-filtered). All three variants' points are intermixed in a loose cloud between roughly 0 and 7 percent return. One point - dip=-1.5% exit=2.0%, plain rule-based - is circled and labeled as the best walk-forward result of all 8 candidates tested." width="720">

- **Dashboard: five panels, regenerated hourly.** `results/trade_dashboard.png`
  is committed automatically, viewable directly on github.com: one
  whole-account net gain/loss panel, plus cumulative realized P&L and
  win/loss-per-ticker each split into separate crypto/stock panels
  rather than blended together - two very different strategies sharing
  one chart said less than two side by side do.

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
│   ├── paper-trade-crypto.yml    # Runs live_trade.py for crypto every ~5min (workflow_dispatch only - no GitHub-side schedule)
│   ├── paper-trade-stocks.yml    # Runs live_trade.py for stocks every ~5min in market hours (workflow_dispatch only - no GitHub-side schedule)
│   ├── retrain-stock-model.yml   # Runs train_stock_model.py weekly
│   └── update-dashboard.yml      # Runs visualize_log.py hourly
├── tests/                        # pytest suite - run with `pytest tests/`
├── docs/                         # Beginner guide, automation setup, risk controls, research tools
├── logs/                         # Generated: trade_log_{crypto,stocks}.csv, equity_log_{crypto,stocks}.csv, retrain_log.csv
├── models/                       # Generated: the saved stock_model.pkl and its metadata
├── results/                      # Generated: trade_dashboard.png (the one to check first), equity_curve.png
│   ├── param_sweep/               #   all optimize.py grid-search output (CSVs + scatter charts)
│   └── walk_forward/              #   all walk_forward.py validation output (CSVs + candidate charts)
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
