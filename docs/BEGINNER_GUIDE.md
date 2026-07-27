# Beginner's guide: how InvestingBot actually works

[← Back to README](../README.md)

This assumes little to no coding background - if you already know what a
script, a workflow, and an API are, you probably don't need this file;
see "Architecture" in the main README instead. This tells you *how and
why* the project works, from the ground up. For *what's* currently
running right now, see "Current live status" in the main README.

## Three kinds of files, and only one of them is "code"

Everything in this repository is one of three things:

1. **Python files (`.py`)** - actual instructions, written as code,
   telling a computer exactly what to do, step by step, when run.
   `live_trade.py`, `main.py`, `optimize.py`, everything under `src/` -
   these are the "brain" of the project.
2. **Workflow files (`.yml`, under `.github/workflows/`)** - not code
   that does anything by itself. They're instructions *for GitHub*,
   telling it when to run one of the Python files above and how to set
   up the computer that runs it. More on this below.
3. **Data files (`.csv`, `.png`, `.pkl`)** - the *output* of running the
   Python files: logs, charts, a saved ML model. I never write these by
   hand; the code produces them, and they change every time it runs.

A natural question at this point: is `paper-trade-crypto.yml` a
**function**? No - a function is a named, reusable piece of Python code
(see `def get_target_position(...):` in `live_trade.py` - that `def` is
what defines one). `paper-trade-crypto.yml` isn't Python at all; it's a
**workflow**, written in a different, much simpler format called YAML,
whose entire job is to tell GitHub's servers "run this Python file, on
this schedule, on a fresh computer you spin up for me."

## What "every 5 minutes, run `paper-trade-crypto.yml`" actually means

GitHub offers a free feature called **GitHub Actions**: I give it a
`.yml` file describing a task, and GitHub boots up a temporary,
disposable Linux computer (they call it a "runner") to carry it out, then
throws that computer away when it's done. Nothing persists on it between
runs - every single run starts from a completely clean machine.

Open `.github/workflows/paper-trade-crypto.yml` and you'll see (in
plain English, translating the YAML):

1. **`on: schedule: cron: "*/5 * * * *"`** - "try to run this every 5
   minutes." That `*/5 * * * *` is **cron syntax**, a very old, very
   standard way of writing recurring schedules (five slots: minute,
   hour, day-of-month, month, day-of-week; `*/5` in the minute slot
   means "every 5th minute"). GitHub's own version of this trigger
   turned out to be unreliable in my testing (see `docs/AUTOMATION.md`
   for how I worked around it).
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
     (more on this in `docs/AUTOMATION.md`, "Logs and the trade
     dashboard").
3. The temporary computer is then destroyed. Five minutes later, a brand
   new one gets created and the whole process repeats from scratch,
   picking up whatever code and data is currently on GitHub.

**Why cron-job.org is also involved:** GitHub's own `schedule:` trigger
(step 1 above) never reliably fired on its own when I tested it
extensively - a real, unexplained platform quirk, not a mistake in the
file. My fix was to add a second, independent trigger to the workflow:
`workflow_dispatch: {}`, which means "also allow this workflow to be
started by an API call, on demand." Then a free external website,
**[cron-job.org](https://cron-job.org)**, acts as an outside alarm clock:
every 5 minutes, *it* sends a request to **GitHub's API** (see glossary
below) saying "please run `paper-trade-crypto.yml` right now" -
completely bypassing GitHub's own flaky scheduler. That's what my
cron-job.org jobs are doing (setup steps in `docs/AUTOMATION.md`).

## What `--strategy day_trading` actually means

`live_trade.py` is a single Python program, but it doesn't do just one
fixed thing - it reads **command-line arguments** (also called flags or
options) that change its behavior each time it's run, the same way you
might customize a coffee order ("size: large, milk: oat") without
needing a different barista for every combination. I'm not writing new
code by passing `--strategy day_trading`; I'm picking a setting inside
the code that's already written.

Inside `live_trade.py`, this line does the reading:
```python
parser.add_argument("--strategy", choices=["rule_based", "ml_filtered", "day_trading", "bollinger_breakout"], default="rule_based")
```
That uses Python's built-in `argparse` tool, which scans whatever I
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
ml_filtered, rule_based, or bollinger_breakout - see `docs/RESEARCH.md`
for what each one means). Look at 5-minute price bars. Treat a 1%
drop as a dip worth buying. Take profit once up 1%. Cut losses if down
3%. And `--execute` means actually place these as real (paper) orders,
not just print what it would have done."* Change any of those words and
I get a different, but equally valid, way to run the exact same program
- that's the whole point of arguments instead of writing a separate
script for every settings combination.

## The full chain, step by step (what happens every 5 minutes)

1. cron-job.org's clock hits a 5-minute mark.
2. It sends a web request to GitHub's API: "run `paper-trade-crypto.yml`
   now, on this branch."
3. GitHub Actions spins up a temporary computer and works through the
   steps described above: download the code, install Python and its
   libraries, then run `live_trade.py` with the settings shown above.
4. Inside that run, for each of the 9 coins, `live_trade.py`:
   - Asks Alpaca (the broker) for the current price (via
     `src/alpaca_data.py`, not Yahoo Finance - see "Crypto support" in
     `docs/AUTOMATION.md` for why).
   - Checks my *actual* current position for that coin against the
     day-trading rule (buy a dip / take profit / stop loss).
   - Decides BUY, SELL, or HOLD.
   - If it's a BUY or SELL and `--execute` was passed, actually places
     that paper order through Alpaca's API (`src/broker.py`).
5. If anything got bought or sold, that gets appended to
   `logs/trade_log.csv`; if the account's current value differs from
   what it was last time, that gets appended to `logs/equity_log.csv`.
   An uneventful run (nothing traded, nothing changed) writes to
   neither file.
6. If either file changed, the workflow **commits** that change (saves a
   snapshot with a message) and **pushes** it back to this GitHub
   repository - that's why `git pull` on my own machine shows new
   "Log crypto trading run" commits over time, authored by the bot, not
   me.
7. The temporary computer gets destroyed. Nothing about this run
   persists anywhere except what got committed to the repository in
   step 6 - the *next* run starts completely fresh and re-derives
   everything (current price, current position, current decision) from
   scratch.

## Why Python?

A few concrete reasons behind the choice, not just familiarity:

- **The entire finance/data-science tooling world is built on it.**
  I didn't have to write a spreadsheet engine, a statistics library, or
  a machine-learning algorithm from scratch - I use `pandas` (tables of
  price data), `numpy` (fast math), `scikit-learn` (the
  `RandomForestClassifier` behind `ml_filtered`), and `matplotlib`
  (charts), all free, all extremely mature, all Python-first.
- **Alpaca and Yahoo Finance both publish official/well-maintained
  Python libraries** (`alpaca-py`, `yfinance`). Python is the language
  most trading and market-data tools support best; picking anything else
  would've meant writing far more code myself for the exact same result.
- **It reads close to plain English**, which matters a lot since the
  goal is to actually study and understand the code, not just run it as
  a black box. Compare `if gain_pct >= args.profit_target:` to the
  equivalent in a lower-level language - Python stays close to how you'd
  say the rule out loud.
- **Speed genuinely doesn't matter here.** This isn't high-frequency
  trading measured in microseconds - it makes one decision every 5
  minutes at most, and almost all of that time is spent *waiting* for
  Alpaca/Yahoo Finance to respond over the network, not computing
  anything. Python being slower than, say, C++ for raw number-crunching
  has zero practical effect on a bot like this.

## Glossary

- **Repository ("repo")** - this whole project folder, tracked by a tool
  called git and hosted on GitHub.
- **Commit** - a saved snapshot of changes to the repo, with a message
  describing what changed. `git commit`.
- **Push / pull** - sending my commits *to* GitHub (`push`), or
  downloading others' (including the bot's own) commits *from* GitHub
  (`pull`).
- **API (Application Programming Interface)** - a way for one program to
  talk to another program automatically, without a human clicking
  anything. "The Alpaca API" is how `live_trade.py` places an order
  without me visiting Alpaca's website.
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
