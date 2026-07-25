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

**New to this project, or newer to coding in general?** Skip down to
"How this actually works" for a plain-English walkthrough of every piece
- what a workflow file is, what those `--strategy day_trading`-style
options mean, why this is all in Python, and how the automation actually
runs every 5 minutes without your computer being on.

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
  not depend on GitHub's own cron (found unreliable in testing for this
  project - see below) or on any computer being on.
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
  `logs/retrain_log.csv`) and manual test runs showed real `ml_filtered`
  decisions for SPY/AAPL/QQQ (all HOLD so far - a legitimate outcome, not
  a failure). See "Machine learning: what it actually does" in "What's
  here" below for what this does and doesn't mean, and "Logs and the
  trade dashboard" for what does/doesn't get recorded going forward - in
  particular, this setup has no real-data track record yet, so
  "automated" here is not the same claim as "proven to work." There's
  also no actual QQQ position open - two QQQ buy orders from early
  manual testing never filled (submitted after market close, `Filled
  Qty: 0.00` on Alpaca's Orders page) - but both are still sitting open
  and could still fill on a future market open. Cancel them on Alpaca's
  Orders page if you don't want that; see "Fixed: BUY no longer stacks"
  below for why the bot itself won't know they're there.
- **Fixed: `--dip-threshold` now actually controls `rule_based` and
  `ml_filtered`.** Previously those two strategies silently ignored the
  flag and always used a hardcoded 3% dip, regardless of what was passed
  on the command line - only `day_trading` respected `--dip-threshold`.
  Both now read the same flag `day_trading` always did. The live stock
  workflow explicitly passes `--dip-threshold -0.03` so this fix doesn't
  silently change its behavior - that was the effective value all along,
  it just wasn't controllable before.
- **Fixed a serious bug: crypto positions were invisible to the bot.**
  `src/broker.py` asked Alpaca for a position using the same symbol
  format used for placing orders (e.g. `"DOGE/USD"`, with a slash), but
  Alpaca's client builds that lookup's URL by plain string concatenation
  with no encoding - the literal `/` split `/positions/DOGE/USD` into an
  invalid 3-segment path, the request failed, and the code's error
  handling silently treated that failure as "no position held" instead
  of surfacing it. Net effect: the bot could never detect a crypto
  position it already held, so the profit-target/stop-loss check never
  ran on it, and a fresh dip signal on a coin already held could trigger
  *another* buy instead of being recognized as "already in this trade."
  This is very likely why real positions (found via the Alpaca paper
  dashboard, not the bot's own - inaccurate - logs) grew large and sat
  unmanaged despite the sell-check logic itself being correct. Fixed by
  stripping the slash for these specific lookups (order placement is
  unaffected - it already worked correctly). Confirmed working on the
  very next cycle after the fix: DOGE was correctly detected and sold
  once its logged unrealized gain cleared the profit target - though
  the position was unusually large (a direct result of this bug letting
  it buy the same dip twice without noticing), and a market order that
  size moved the price enough while filling that the trade closed at a
  real loss despite a positive number at decision time. LTC sold later
  the same way, at a much more typical size, for a real profit.
- **Fixed: BUY no longer stacks on top of an already-open, unfilled
  order.** `decide()` only ever checked *filled* position size, never
  whether an order for that symbol was already sitting open/unfilled -
  found via two real stale QQQ orders (submitted after market close,
  queued for the next session, never filled) that a later BUY signal
  would have had no way of knowing about and could have duplicated.
  `Broker.has_open_order()` now checks before every BUY and skips if one
  already exists. This doesn't retroactively cancel any order already
  sitting open - cancel those manually on Alpaca's Orders page if you
  don't want them to fill; this only stops *new* ones from stacking on
  top going forward.
- **Dashboard: live and automated, regenerated hourly.** A fourth
  workflow, `update-dashboard.yml`, runs `visualize_log.py --baseline
  100000` and commits `results/trade_dashboard.png` back to the repo -
  view it directly on github.com for a chart that's never more than an
  hour stale, no local setup needed. Driven by its own cron-job.org job
  hitting its `workflow_dispatch` endpoint, same pattern as the other
  three workflows, confirmed firing successfully on schedule.
- **Current results snapshot (will be stale by the time you read this -
  check `results/trade_dashboard.png` for the live number):** the
  account is up **+$357.00** against its $100,000 funding baseline. That
  total is not the same as "the strategy has an edge" - only two trades
  have actually closed so far, and they tell two different stories
  depending on whether you count the one affected by the bug above.
  Counting both, realized P&L is **-$857.64** (dominated by DOGE's
  oversized, bug-inflated loss); excluding the flagged DOGE trade,
  realized P&L from LTC alone is **+$41.30**. Neither number is "the
  real" one on its own - see "Logs and the trade dashboard" below for
  why both are shown side by side rather than picking one. The account
  being up overall right now is mostly unrealized gains on whatever's
  still open, not proof the closed trades are profitable.
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

## How this actually works (a plain-English walkthrough)

The section above tells you *what's* currently running. This tells you
*how and why*, from the ground up, assuming little to no coding
background. If you already know what a script, a workflow, and an API
are, skip to "What's here" below.

### Three kinds of files, and only one of them is "code"

Everything in this repository is one of three things:

1. **Python files (`.py`)** - actual instructions, written as code,
   telling a computer exactly what to do, step by step, when run. `live_trade.py`,
   `main.py`, `optimize.py`, everything under `src/` - these are the
   "brain" of the project.
2. **Workflow files (`.yml`, under `.github/workflows/`)** - not code
   that does anything by itself. They're instructions *for GitHub*,
   telling it when to run one of the Python files above and how to set
   up the computer that runs it. More on this below.
3. **Data files (`.csv`, `.png`, `.pkl`)** - the *output* of running the
   Python files: logs, charts, a saved ML model. Nobody writes these by
   hand; the code produces them, and they change every time it runs.

A natural question at this point: is `paper-trade-crypto.yml` a
**function**? No - a function is a named, reusable piece of Python code
(see `def get_target_position(...):` in `live_trade.py` - that `def` is
what defines one). `paper-trade-crypto.yml` isn't Python at all; it's a
**workflow**, written in a different, much simpler format called YAML,
whose entire job is to tell GitHub's servers "run this Python file, on
this schedule, on a fresh computer you spin up for me."

### What "every 5 minutes, run `paper-trade-crypto.yml`" actually means

GitHub offers a free feature called **GitHub Actions**: you give it a
`.yml` file describing a task, and GitHub will boot up a temporary,
disposable Linux computer (they call it a "runner") to carry it out, then
throw that computer away when it's done. Nothing persists on it between
runs - every single run starts from a completely clean machine.

Open `.github/workflows/paper-trade-crypto.yml` and you'll see (in
plain English, translating the YAML):

1. **`on: schedule: cron: "*/5 * * * *"`** - "try to run this every 5
   minutes." That `*/5 * * * *` is **cron syntax**, a very old, very
   standard way of writing recurring schedules (five slots: minute,
   hour, day-of-month, month, day-of-week; `*/5` in the minute slot
   means "every 5th minute"). GitHub's own version of this trigger
   turned out to be unreliable in testing for this project (see below
   for how that's worked around).
2. **`steps:`** - a numbered list of things to do, in order, on that
   fresh temporary computer:
   - `actions/checkout@v4` - download a fresh copy of this repository's
     code onto the temporary computer.
   - `actions/setup-python@v5` - install Python 3.12 onto it (it starts
     with nothing installed).
   - `pip install -r requirements.txt` - install this project's
     dependencies: the free, third-party Python libraries it relies on
     (pandas, alpaca-py, scikit-learn, etc. - see `requirements.txt`).
   - **`python live_trade.py --ticker BTC ETH SOL ... --strategy
     day_trading ... --execute`** - actually run the bot. This is the
     one line that does the real work; everything else in the file is
     just setting the stage for it.
   - A final step that saves any new log rows back to the repository
     (more on this in "Logs and the trade dashboard" above).
3. The temporary computer is then destroyed. Five minutes later, a brand
   new one is created and the whole process repeats from scratch,
   picking up whatever code and data is currently on GitHub.

**Why cron-job.org is also involved:** GitHub's own `schedule:` trigger
(step 1 above) was tested extensively in this project and never reliably
fired on its own - a real, unexplained platform quirk, not a mistake in
the file. The fix was to add a second, independent trigger to the
workflow: `workflow_dispatch: {}`, which means "also allow this workflow
to be started by an API call, on demand." Then a free external website,
**[cron-job.org](https://cron-job.org)**, acts as an outside alarm clock:
every 5 minutes, *it* sends a request to **GitHub's API** (see glossary
below) saying "please run `paper-trade-crypto.yml` right now" -
completely bypassing GitHub's own flaky scheduler. That's what the
cron-job.org jobs you set up are doing.

### What `--strategy day_trading` actually means

`live_trade.py` is a single Python program, but it doesn't do just one
fixed thing - it reads **command-line arguments** (also called flags or
options) that change its behavior each time it's run, the same way you
might customize a coffee order ("size: large, milk: oat") without
needing a different barista for every combination. You're not writing
new code by passing `--strategy day_trading`; you're picking a setting
inside the code that's already written.

Inside `live_trade.py`, this line does the reading:
```python
parser.add_argument("--strategy", choices=["rule_based", "ml_filtered", "day_trading", "bollinger_breakout"], default="rule_based")
```
That uses Python's built-in `argparse` tool, which scans whatever you
typed after `python live_trade.py` and turns it into values the rest of
the program can use. So the full command GitHub actually runs:

```bash
python live_trade.py --ticker BTC ETH SOL DOGE LTC AVAX LINK XRP DOT \
  --strategy day_trading --interval 5m \
  --dip-threshold -0.01 --profit-target 0.01 --stop-loss 0.03 \
  --execute
```
translates to, in plain English: *"Run the live_trade.py program. Check
these 9 coins. Use the day_trading decision logic (as opposed to
ml_filtered, rule_based, or bollinger_breakout - see 'What's here'
below for what each one means). Look at 5-minute price bars. Treat a 1%
drop as a dip worth buying. Take profit once up 1%. Cut losses if down
3%. And `--execute` means actually place these as real (paper) orders,
not just print what it would have done."* Change any of those words and
you get a different, but equally valid, way to run the exact same
program - that's the whole point of arguments instead of writing a
separate script for every settings combination.

### The full chain, step by step (what happens every 5 minutes)

1. cron-job.org's clock hits a 5-minute mark.
2. It sends a web request to GitHub's API: "run `paper-trade-crypto.yml`
   now, on this branch."
3. GitHub Actions spins up a temporary computer and works through the
   steps described above: download the code, install Python and its
   libraries, then run `live_trade.py` with the settings shown above.
4. Inside that run, for each of the 9 coins, `live_trade.py`:
   - Asks Alpaca (the broker) for the current price (via
     `src/alpaca_data.py`, not Yahoo Finance - see "Crypto support"
     below for why).
   - Checks your *actual* current position for that coin against the
     day-trading rule (buy a dip / take profit / stop loss).
   - Decides BUY, SELL, or HOLD.
   - If it's a BUY or SELL and `--execute` was passed, actually places
     that paper order through Alpaca's API (`src/broker.py`).
5. If anything was bought or sold, that gets appended to
   `logs/trade_log.csv`; if the account's current value differs from
   what it was last time, that gets appended to `logs/equity_log.csv`.
   An uneventful run (nothing traded, nothing changed) writes to
   neither file.
6. If either file changed, the workflow **commits** that change (saves a
   snapshot with a message) and **pushes** it back to this GitHub
   repository - that's why `git pull` on your own machine shows new
   "Log crypto trading run" commits over time, authored by the bot, not
   you.
7. The temporary computer is destroyed. Nothing about this run persists
   anywhere except what got committed to the repository in step 6 - the
   *next* run starts completely fresh and re-derives everything (current
   price, current position, current decision) from scratch.

### Why Python?

A few concrete reasons behind the choice, not just familiarity:

- **The entire finance/data-science tooling world is built on it.**
  This project didn't have to write a spreadsheet engine, a statistics
  library, or a machine-learning algorithm from scratch - it uses
  `pandas` (tables of price data), `numpy` (fast math), `scikit-learn`
  (the `RandomForestClassifier` behind `ml_filtered`), and `matplotlib`
  (charts), all free, all extremely mature, all Python-first.
- **Alpaca and Yahoo Finance both publish official/well-maintained
  Python libraries** (`alpaca-py`, `yfinance`). Python is the language
  most trading and market-data tools support best; picking anything else
  would mean far more code to write ourselves for the exact same result.
- **It reads close to plain English**, which matters a lot if the goal
  is to actually study and understand the code, not just run it as a
  black box. Compare `if gain_pct >= args.profit_target:` to
  the equivalent in a lower-level language - Python stays close to how
  you'd say the rule out loud.
- **Speed genuinely doesn't matter here.** This isn't high-frequency
  trading measured in microseconds - it makes one decision every 5
  minutes at most, and almost all of that time is spent *waiting* for
  Alpaca/Yahoo Finance to respond over the network, not computing
  anything. Python being slower than, say, C++ for raw number-crunching
  has no practical effect on a bot like this.

### The big picture: two separate pipelines that share code

- **Backtesting (research, no real money, no live prices):**
  `main.py` / `optimize.py` → `src/data.py` (fetch *historical* data) →
  `src/features.py` (compute indicators like RSI/SMA) →
  `src/strategies.py` (simulate what a strategy *would have* done) →
  `src/backtest.py` (score it: return, Sharpe, drawdown). Nothing here
  ever touches a real broker.
- **Live trading (paper money, real live prices, right now):**
  `live_trade.py` → `src/alpaca_data.py` or `src/data.py` (fetch
  *current* data) → `src/features.py` (same indicator code) →
  `src/strategies.py` or `src/model.py` (make today's actual decision)
  → `src/broker.py` (place the real - paper - order via Alpaca) →
  `logs/*.csv` (record what happened).

Both pipelines reuse the same feature/strategy code on purpose - it's
the only way to trust that a backtest result says anything about what
the live version will actually do; if they used separate logic, a good
backtest wouldn't mean anything about live behavior.

### Glossary

- **Repository ("repo")** - this whole project folder, tracked by a tool
  called git and hosted on GitHub.
- **Commit** - a saved snapshot of changes to the repo, with a message
  describing what changed. `git commit`.
- **Push / pull** - sending your commits *to* GitHub (`push`), or
  downloading others' (including the bot's own) commits *from* GitHub
  (`pull`).
- **API (Application Programming Interface)** - a way for one program to
  talk to another program automatically, without a human clicking
  anything. "The Alpaca API" is how `live_trade.py` places an order
  without anyone visiting Alpaca's website.
- **Endpoint** - a specific web address an API call gets sent to, e.g.
  `https://paper-api.alpaca.markets`.
- **Workflow / GitHub Actions** - GitHub's built-in automation feature;
  each `.yml` file under `.github/workflows/` is one workflow.
- **Cron / cron syntax** - a decades-old, widely used way to write
  recurring schedules as five symbols (minute, hour, day, month,
  weekday); `*/5 * * * *` = "every 5 minutes."
- **Paper trading** - trading with fake money against real, live prices
  - for practice and testing, with zero real financial risk.
- **Backtest** - testing a strategy against *past* price data to see how
  it would have performed, without waiting for real time to pass.
- **Model / machine learning model** - a mathematical pattern-matcher
  trained on past examples to make a prediction - here, "will this dip
  bounce back?"
- **Threshold** - a cutoff number used to turn a continuous prediction
  into a yes/no decision (e.g. "only buy if the model's confidence is
  above 0.57").
- **`.env` file** - a local, git-ignored file holding secret values (API
  keys) so they never get committed to the repository by accident.
- **`requirements.txt`** - the list of third-party Python libraries this
  project needs; `pip install -r requirements.txt` installs all of them
  in one command.

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
  features. Windows are defined in bars, not calendar days, so a
  "20-period" moving average means whatever 20 *bars* of the requested
  `--interval` spans - a 20-day trend on daily data, a 20-hour trend on
  hourly data, or (the live crypto case) a rolling 100-minute window on
  5-minute bars: 20 x 5 minutes, continuously updated as each new bar
  arrives and the oldest one drops off, not anchored to any fixed clock
  time.
- `src/strategies.py` - five strategies:
  1. **Buy & hold**
  2. **Rule-based dip buy** - buy when price is below its 20-period
     moving average by at least `--dip-threshold` (defaults to 2%), sell
     once it recovers back above the average (mean-reversion exit,
     independent of what you paid). On real recent crypto/5-minute data,
     even a 2% threshold rarely fires - that timeframe's typical moves
     are well under 1%, so this strategy is a better fit for daily bars
     than 5-minute ones.
  3. **ML-filtered dip buy** - same rule and same `--dip-threshold`, but
     only acts on a dip if a model trained to predict "will this bounce?"
     is confident enough.
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
  - Its dip threshold (`--dip-threshold`, controllable like the other
    strategies - see "Current live status" above) still needs to be
    sized for the timeframe it runs on: a threshold that makes sense on
    daily bars would rarely fire on 5-minute crypto data, where typical
    moves are much smaller - one more reason ML stayed off crypto and
    went to stocks instead.
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
- `visualize_log.py` - turns `logs/equity_log.csv` and
  `logs/trade_log.csv` into a 3-panel dashboard PNG (equity over time,
  cumulative realized P&L, win/loss per ticker). See "Logs and the trade
  dashboard" below.

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
Alpaca paper dashboard to see the fill. See "Logs and the trade dashboard"
below for what gets recorded and where.

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
5. Each run may append to `logs/equity_log.csv` (if the account's value
   changed) and/or `logs/trade_log.csv` (if it actually bought or sold
   something) - an uneventful run writes to neither. Whenever either
   file does change, the workflow commits that update back to the repo,
   so `git pull` locally will show new commits with a "Log ... trading
   run" message over time. That's the automated bot committing its own
   log, not you.
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
what the market is actually doing - pull real price data (e.g. via
`main.py` or `optimize.py`, both of which fetch it fresh) rather than
guessing. `trade_log.csv` itself only records actual BUY/SELL decisions
now (see "Logs and the trade dashboard"), so it's no longer a dense price
history the way it briefly was.

**Worth knowing before you tighten these further:** more frequent
trading means more round trips, and every round trip pays Alpaca's
crypto spread/fee (roughly 0.15-0.25% each way, so ~0.3-0.5% per full
buy-sell cycle). If `--profit-target` is smaller than that fee drag, the
strategy loses money **on average even when directionally correct** -
there's a real floor below which "more trades" just means "more fee
payments," not more profit. The 1.0% target above has been kept
deliberately above that floor; going much lower trades against the fee
structure, not with it. Real fills so far land toward the higher end of
that fee range - one closed trade paid about 0.25%, another about 0.44%
- worth treating the floor as a range to stay clear of, not a precise
number to shave against.

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

### Logs and the trade dashboard

Every `live_trade.py` run writes to two separate CSVs, both git-tracked so
`git pull` shows the bot's own history over time:

- **`logs/equity_log.csv`** - `timestamp_utc`, `mode`,
  `portfolio_value_usd`, `cash_usd`, at most one row per run (not per
  ticker) - and only when the account value actually differs from the
  last logged row. Most runs change nothing (no trade, no open position
  whose price moved), so most runs write nothing here at all; a real
  change, even a small one, is still logged immediately. This keeps the
  file a clean time series of "what was the account worth, and when did
  that change" without a row for every unchanged 5-minute check-in.
- **`logs/trade_log.csv`** - one row **per actual BUY/SELL decision**
  (dry-run or executed): `timestamp_utc`, `mode`, `asset_class`, `ticker`,
  `strategy`, `action`, `price_usd`, `notional_usd`,
  `position_qty_before`, `avg_entry_price_usd`, `unrealized_gain_pct`
  (already a percentage, e.g. `1.08` means +1.08%, not `0.0108`),
  `order_placed` (whether it was a live order vs. a dry run), and `notes`
  - a manual annotation slot, empty by default, never written by the bot
    itself. Use it to flag a specific trade as unrepresentative (e.g.
    "position was 2x intended size due to a since-fixed bug") without
    ever deleting or hiding the real result - `visualize_log.py` reads
    this to show both the honest full history and a "how is the
    strategy itself actually doing" view side by side, see below.
  **HOLD decisions are not logged here** - see below for why.

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
account produces zero new rows run after run. The pre-redesign log,
kept for reference (and because its header didn't actually match its
data - a real bug that motivated this rewrite), is archived at
`logs/trade_log_archive_pre_2026-07-25.csv`.

**`python visualize_log.py`** turns both files into a three-panel PNG
(`results/trade_dashboard.png` by default): net account gain/loss,
cumulative realized P&L from executed trades, and win/loss counts per
ticker. Run it locally anytime for an on-demand snapshot - harmless, no
network/broker access needed, just reads the two log files.

**The first panel's baseline matters and is easy to misread.** By
default it's equity minus the *first* row of `logs/equity_log.csv` -
i.e. "gain/loss since equity logging happened to start," which is not
the same as "since you funded the account," especially if trades were
already open before logging began. Pass `--baseline 100000` (or
whatever your actual starting cash was) to measure from your real
starting point instead - the title changes to make clear which one
you're looking at. Both are valid, they just answer different
questions - but showing only the "since tracking began" one risks
looking like it disagrees with what Alpaca's own dashboard says, when
both numbers are actually correct, just measuring from different
starting points. Use `--baseline` whenever you want the number that
matches Alpaca's own total account P&L.

It also runs on a schedule: `.github/workflows/update-dashboard.yml`
regenerates and commits `results/trade_dashboard.png` roughly hourly
(with `--baseline 100000`, via an external scheduler - GitHub's own
`schedule:` trigger isn't reliable enough on its own here either, same
as the trading workflows), so `results/trade_dashboard.png` on GitHub
is close to current without needing to run anything locally - just open
that file's page on github.com. This is deliberately a slower cadence
than the 5-minute trading workflows: one image commit an hour is a
small, bounded cost, where committing an image every 5 minutes forever
would not be.

### Stock automation: ML with periodic retraining

Stocks run a different strategy than crypto on purpose - `ml_filtered`
instead of the rule-based `day_trading`, so this project has one live
example of each approach to actually compare over time, and so the ML
path gets exercised somewhere: crypto's 5-minute bars move far less per
bar than daily stock bars do, so a dip threshold sized for daily data
(the live stock workflow runs at 3% - see "Current live status" above)
would rarely fire on 5-minute crypto.

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

## Security: who can see what, and who can change what

A public GitHub repository means the source code is visible to anyone -
every strategy, every threshold, every workflow file. That does not mean
credentials are exposed; a few separate mechanisms decide what actually
is and isn't visible or changeable:

- **API keys and secrets are never in the code, and are not visible to
  anyone once saved.** They belong in **GitHub Actions secrets**
  (Settings -> Secrets and variables -> Actions), a separate, encrypted
  vault from the repository itself. A secret's value can never be viewed
  again after saving - not by other people, not by the account owner,
  only *used* by a workflow at runtime. If a workflow's console output
  ever tried to print one, GitHub automatically detects and masks it as
  `***` before the log is shown, public repo or not. This is why
  `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` live there rather than in
  `.env` (which is git-ignored precisely so it's never committed by
  accident either).
- **Tokens used by an external scheduler (e.g. cron-job.org) live
  entirely outside this repository** - in that service's own account
  configuration, invisible to anyone browsing GitHub. Such a token is
  still a real, live credential: anyone who obtained it could trigger
  the linked workflows on demand. Scoping it as narrowly as
  possible - e.g. "Actions: read and write" on only this one
  repository, nothing else - limits the damage a leaked token could
  do to spam-triggering workflow runs, not pushing code or reaching a
  broker account directly.
- **Only explicitly added collaborators can push or edit code.** Check
  Settings -> Collaborators and teams on GitHub to see exactly who
  currently has write access - by default, that's just the repository
  owner. Being public means anyone can fork the repo and open a pull
  request proposing a change, but a pull request is only a proposal
  sitting in a queue: nothing merges into the repository unless someone
  with write access reviews and approves it.
- **Making a repository private** (Settings -> General -> Danger Zone ->
  Change visibility) hides the source code from public view entirely.
  It's purely a visibility toggle - it doesn't touch secrets or
  workflows, and the automation described throughout this README
  continues to work identically either way.

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
