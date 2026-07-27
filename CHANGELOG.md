# Changelog

Uses [semantic versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
The `0.x.x` line is "Version Richards"; `1.0.0`+ becomes "Version Giroux."

**What's required before `1.0.0` gets declared** (not yet met):
- Dozens to hundreds of real closed paper trades on the strategy
  actually running live - not the 3 currently on record, and none yet
  under the 0.7.0 thresholds - with positive net expectancy after real
  observed costs/slippage, not backtested ones.
- Walk-forward validation across multiple distinct, non-overlapping time
  periods, repeated more than once. `walk_forward.py` (added 0.6.2) did
  this for the first time in 0.7.0, across 6 real-data windows spanning
  Aug 2025-Jul 2026 - a real start, not the finish line. Still needed:
  re-validating as more live history accumulates, and explicit coverage
  of both a trending and a choppy/range-bound stretch, not just whatever
  regime the most recent real year happened to contain.
- No known open correctness bugs (true as of 0.5.2).

## Version Richards 0.9.3 - 2026-07-27

- Clarified: of the 8 stock candidates walk-forward tested this session,
  `rule_based` on 5-minute bars (`dip=-1.5% exit=2.0%`) is the clear
  best - its ticker-window loss rate (17.5%) is well below every other
  candidate's (25-32%), while its average return (3.06%/ticker) still
  sits mid-pack rather than being traded away for that consistency.
  Previously the README/`docs/RESEARCH.md` reported all 8 candidates
  side by side with no single one called out, which understated a real
  finding: this one is a meaningfully better result than the rest, not
  just a different one. Still explicitly **not** a proven edge - one
  year of 5-minute data and 8.6 average trades/ticker is a thin sample -
  and stocks remain paused either way.
- `results/walk_forward_stocks_summary.png`,
  `results/param_sweep_overview_stocks_5m_all.png`, and
  `results/param_sweep_overview_stocks_daily_all.png` regenerated to
  visually mark this candidate (outlined/circled with an annotation)
  instead of showing all 8 with no distinction. README's "Current live
  status" table now has a dedicated row for it.

## Version Richards 0.9.2 - 2026-07-27

- README given a visual pass - not a single word of its actual content
  changed. Added: badges (Python version, test count, paper-trading-only
  mode, demonstrated-edge status) in a centered header block; a "Contents"
  section linking to every major heading; horizontal-rule dividers
  between sections; the existing "Not investment advice" and Disclaimer
  paragraphs converted to GitHub's `[!WARNING]`/`[!NOTE]` alert-style
  blockquotes (same text, just visually set apart). Purely presentational.

## Version Richards 0.9.1 - 2026-07-27

- Fixed: `live_trade.py` and `main.py` had no way to actually configure
  `exit_threshold` (or `rule_based`'s stop-loss/cooldown) for live or
  demo trading - `--dip-threshold` was the only tunable flag, so every
  `rule_based`/`ml_filtered` run silently used `exit_threshold=0.0` no
  matter what. This meant none of this session's extensive stock
  validation work (which explored exit thresholds like 1%/2%, plus
  stop-loss/cooldown) could ever actually be deployed - a real gap, not
  just a missing convenience. Added `--exit-threshold` to both scripts,
  and `--rule-stop-loss`/`--rule-stop-cooldown` to `live_trade.py`,
  matching `optimize.py`'s/`walk_forward.py`'s own flag names exactly so
  a validated combo can be deployed with the same numbers, no
  translation. All default to the original no-exit-threshold/no-stop
  behavior, so nothing changes for existing callers that don't pass them.
- Fixed: `tests/test_data.py`'s module docstring and one test's name
  claimed "non-crypto tickers should never touch Alpaca at all" - false
  since 0.8.4 added `get_stock_bars_range()` for intraday stock
  requests. Corrected the docstring/test name (`test_daily_stock_never_
  calls_alpaca`) and added 3 new tests covering the actual current
  behavior (intraday stock requests do try Alpaca first, with the same
  fallback logic crypto already had).
- Added: `tests/test_alpaca_data.py` - `src/alpaca_data.py` had zero
  test coverage at all despite being the sole data source
  `get_price_data_smart()` trusts first for every intraday request. 9
  new tests cover `_fetch_bars`'s MultiIndex handling, empty-response
  errors, the crypto staleness check, and that stock requests explicitly
  ask for the free IEX feed. 71 tests passing (up from 59).
- Full codebase read-through (every `.py` file, ~4300 lines) looking for
  further correctness bugs; nothing else found.

## Version Richards 0.9.0 - 2026-07-27

- **Stock validation concluded (for now): 8 candidates walk-forward
  tested this session, none cleared the bar.** Daily and 5-minute bars,
  plain `rule_based`, `rule_based` with a stop-loss + re-entry cooldown,
  and `ml_filtered` (the same rule gated by a trained model) all landed
  in roughly the same 17-32% ticker-window loss rate - no combination of
  return, consistency, and real trade count stood out as robust. This is
  an honest result, not a dead end: dip-buying these 9 stocks hasn't
  shown a real edge yet at either resolution, with or without an ML
  filter - the same place crypto's own validation started before
  `walk_forward.py` eventually found something worth trusting. Stocks
  remain paused; nothing here resumes live stock trading on its own.
- Added 3 new committed charts summarizing the entire search:
  [`results/walk_forward_stocks_summary.png`](results/walk_forward_stocks_summary.png)
  (all 8 candidates' return/consistency side by side),
  [`results/param_sweep_overview_stocks_daily_all.png`](results/param_sweep_overview_stocks_daily_all.png)
  and
  [`results/param_sweep_overview_stocks_5m_all.png`](results/param_sweep_overview_stocks_5m_all.png)
  (all three daily/5-minute grid-search variants combined). Every
  underlying grid and walk-forward run behind these charts is also
  committed as CSV - see `docs/RESEARCH.md`'s "Final tally" section for
  the full list and the important caveats about differing held-out
  periods across variants (particularly `ml_filtered`, which stops
  before its model's own training window rather than reaching the
  present the way every other candidate here does).
- README's stock section rewritten to lead with this consolidated
  conclusion instead of a running list of individual candidates.

## Version Richards 0.8.9 - 2026-07-27

- Added: `--end` to `train_stock_model.py` - trains up through a given
  date instead of always through today, so a validation-only run can
  hold back a recent chunk of data on purpose (for `optimize.py`/
  `walk_forward.py` to test against data the model genuinely never saw).
  The live retrain workflow never passes this, so its always-train-
  through-today behavior is unchanged.
- Added: `data_end` to the saved model's metadata - the actual last
  training date, which isn't always `trained_at` once `--end` can differ
  from "today." `docs/RESEARCH.md`'s leakage-avoidance guidance now
  points at this field directly instead of computing it from
  `trained_at`/`lookback_days`.

## Version Richards 0.8.8 - 2026-07-27

- Added: `--interval` to `train_stock_model.py` (default `1d`, unchanged
  from before - the live retrain workflow doesn't pass this flag, so its
  behavior is identical). A non-daily interval now pulls from Alpaca
  first via `get_price_data_smart()` (needed to test `--strategy
  ml_filtered` at 5-minute resolution, the same way `optimize.py`/
  `walk_forward.py` already can for `rule_based`). `--out` now defaults
  to `models/stock_model_<interval>.pkl` for any non-daily interval,
  instead of the daily default `models/stock_model.pkl` - so an
  experimental 5-minute training run can never overwrite the model
  `live_trade.py` actually trades with.
- Documented clearly (module docstring + `--horizon`/`--bounce-pct` help
  text): both are expressed in bars, not calendar time. The daily
  defaults (`horizon=10`, `bounce_pct=3%`) mean "3%+ within 10 trading
  days" - a wildly different, much larger ask over 10 five-minute bars
  (50 minutes). Recalibrate both before training a non-daily model, the
  same lesson `--dip-threshold`/`--exit-threshold` already needed at 5m
  resolution earlier this session.

## Version Richards 0.8.7 - 2026-07-27

- Added: `--strategy ml_filtered` support to `optimize.py` and
  `walk_forward.py`, after 7 straight `rule_based` candidates (3 daily,
  2 five-minute, 2 with stop-loss/cooldown added) failed to show a
  robust walk-forward edge. `ml_filtered` loads an already-trained,
  already-saved model (`--model-path`, default `models/stock_model.pkl`
  - the exact model `live_trade.py` would use, not a fresh one trained
  just for this search) and sweeps `--dip-values`/`--exit-values`
  against `ml_filtered_dip_buy()`'s model-gated entries, the same way
  `rule_based`'s plain rule was swept. `position_for_params()` now
  accepts optional `model`/`threshold` arguments (kept separate from
  the swept `params` dict, since a model object isn't something
  `optimize.py` can write to a CSV column).
- **Caveat worth knowing before running this**: `train_stock_model.py`
  trains on the trailing `--lookback-days` (730 by default) up to
  whenever it last ran. Evaluating `ml_filtered` over a range that
  overlaps that training window isn't a clean out-of-sample test - the
  model may have partially fit patterns specific to that exact regime.
  For a fair test, `--end` should stay before the saved model's own
  training start (`models/stock_model.pkl.meta.json`'s `trained_at`
  minus `lookback_days`).

## Version Richards 0.8.6 - 2026-07-27

- Fixed: `results/walk_forward_winner.png` (the crypto walk-forward chart)
  labeled each bar by its window's **start** date, so the final window
  (2026-05-28 -> 2026-07-27) only ever showed "May '26" - June and July
  2026 never appeared as labels even though the chart's own title
  correctly states the data runs through July 2026, and the underlying
  `results/walk_forward.csv` data was always correct. Regenerated with
  window **end** dates as labels instead; no data changed, cosmetic only.
- Added: `stop_cooldown_bars` to `rule_based_dip_buy()`
  (`src/strategies.py`) - real walk-forward evidence found the new
  0.8.5 stop-loss could backfire during a sustained decline: SPY's
  2019-2021 window went from -3.2% (no stop-loss) to -27.4% (10% stop,
  no cooldown), because the strategy re-buys immediately after a
  stop-out if the dip condition still holds, turning one long unrealized
  drawdown into several smaller realized losses plus extra transaction
  costs. `stop_cooldown_bars` blocks re-entry for N bars after a
  stop-loss exit specifically (not after a normal recovery exit).
  Defaults to `0` (unchanged behavior). Added `--stop-cooldown-values`
  (`optimize.py`) and `--rule-stop-cooldown` (`walk_forward.py`), both
  optional and only meaningful alongside a stop-loss.
- Added: 1 test for the cooldown blocking re-entry, then correctly
  releasing it after N bars. 59 tests passing.

## Version Richards 0.8.5 - 2026-07-27

- Added: optional `stop_loss` parameter to `rule_based_dip_buy()`
  (`src/strategies.py`) - a hard downside cap based on actual entry
  price, the same protection `dip_buy_profit_target` (crypto's strategy)
  has always had. `rule_based` never had one: it only ever exits on mean
  reversion (price recovering back above the SMA), so a real walk-forward
  run against daily stock bars this session found ticker/window
  drawdowns as deep as -40% (XOM) while the strategy just waited for a
  recovery that eventually came, but easily might not have. Defaults to
  `None` (the original behavior, byte-for-byte) - nothing changes unless
  a caller actually opts in.
- Added: `--stop-loss-values` (`optimize.py`) and `--rule-stop-loss`
  (`walk_forward.py`), both `--strategy rule_based`-only and optional, so
  a stop-loss can be swept/validated alongside dip/exit the same way
  crypto's three parameters already are. A separate flag from
  day_trading's own required `--stop-loss` in both scripts, specifically
  so validating a `rule_based` combo never silently picks up a
  crypto-sized stop-loss you didn't ask for.
- Added: 3 tests covering the new parameter - stop-loss firing before a
  recovery would have, `stop_loss=None` giving byte-for-byte the same
  result as before this parameter existed, and the `position_for_params`
  dispatch actually passing it through. 58 tests passing.
- Fixed (caught before committing): a stray `%` in `optimize.py`'s new
  `--stop-loss-values` help text ("-40% while...") crashed `--help`
  entirely - argparse treats help strings as `%`-format templates, so a
  literal `%` needs escaping as `%%`.

## Version Richards 0.8.4 - 2026-07-27

- Added: `get_stock_bars_range()` in `src/alpaca_data.py` - Alpaca's
  historical stock bars (free `DataFeed.IEX` feed), the same role
  `get_crypto_bars_range()` already plays for crypto. `src/data.py`'s
  `get_price_data_smart()` now tries Alpaca first for a stock ticker too,
  but only when the request is intraday (`interval != "1d"`) - Yahoo's
  daily stock history is already decades deep, so there's no 60-day cap
  to route around for a daily request. Requested because the daily-bar
  `rule_based` stock search below trades so rarely for some tickers (KO,
  JNJ) that most walk-forward windows never traded at all - a finer bar
  size gives the strategy more signal to actually be tested on, the same
  problem Alpaca's crypto bars already solved for the 5-minute crypto
  strategy. Not yet run for real (needs `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`
  in a local `.env`, which this environment doesn't have) - the next step
  is a real `walk_forward.py --strategy rule_based --interval 5m` run.
- Added: real committed stock validation evidence, gathered the same way
  the 0.7.0 crypto combo was -
  [`results/param_sweep_stocks.csv`](results/param_sweep_stocks.csv) (top
  15 of an 18-combo `optimize.py --strategy rule_based` grid search,
  2022-01-01 to 2026-07-27 held out) and
  [`results/walk_forward_stocks.csv`](results/walk_forward_stocks.csv)
  (three candidate combos - dip=-3%/exit=1%, dip=-6%/exit=1%,
  dip=-8%/exit=1% - each walk-forward validated across the same 9
  tickers and 7 sequential windows spanning 2015-01-01 to 2026-07-27).
  Unlike crypto, **no combo here has been picked yet**: the highest-return
  combo (-3%/1%) is inconsistent (20 of 63 ticker-windows were losers,
  32%), the safest-looking one (-8%/1%) trades so rarely that most of its
  apparent safety is really "never got tested" (KO's one trade in 11
  years), and the middle ground (-6%/1%) split the difference on both
  return and consistency rather than clearly beating either extreme. See
  `docs/RESEARCH.md` for the full comparison. Charts mirroring
  `results/param_sweep_overview.png` and `results/walk_forward_winner.png`
  are committed too:
  [`results/param_sweep_overview_stocks.png`](results/param_sweep_overview_stocks.png)
  and
  [`results/walk_forward_stocks_candidate.png`](results/walk_forward_stocks_candidate.png)
  (the -6%/1% candidate, chosen for the chart only because it was the
  most recently tested, not because it won).
- Stocks remain paused; none of this resumes stock automation on its own.

## Version Richards 0.8.3 - 2026-07-27

- Fixed: `docs/RESEARCH.md`'s `optimize.py --strategy rule_based`
  example command for stocks was missing `--interval 1d` - since
  `optimize.py`'s own default is `5m` (crypto's interval), running that
  example as written for a 2015-2024 stock range hit the exact same
  Yahoo 60-day intraday cap crypto ran into, just for the wrong reason.
  Found running it for real. Added `--interval 1d` to the example and a
  warning note explaining why.
- Added: `--interval`'s help text in both `optimize.py` and
  `walk_forward.py` now explicitly calls out that leaving it at the
  crypto-matching `5m` default for a multi-year stock search will hit
  that same cap, instead of only documenting it in prose elsewhere.
- Documentation/help-text only; no code behavior changed.

## Version Richards 0.8.2 - 2026-07-27

- Changed: stock ticker list grew from 3 (SPY, AAPL, QQQ) to 9, adding
  JPM (financials), XOM (energy), JNJ (healthcare), KO (consumer
  staples), CAT (industrials), and DIS (media/consumer discretionary) -
  deliberately spanning sectors that don't already overlap with the
  existing broad-market/tech names, the same "a setting that only works
  on one ticker isn't a real edge" principle `optimize.py` already
  applies to crypto, and a direct response to the correlation problem
  that same crypto validation surfaced (several coins moving together
  in the same market swing, inflating how independent the evidence
  actually was - sector-diverse stocks are less likely to share that
  failure mode). Updated in `paper-trade-stocks.yml`,
  `retrain-stock-model.yml`, and `train_stock_model.py`'s own
  `--ticker` default, plus the `optimize.py`/docs examples referencing
  the old 3-ticker list.
- Config-only change while stock automation is already paused (see
  0.8.0/0.8.1) - takes effect whenever it resumes, no live behavior
  changed today.

## Version Richards 0.8.1 - 2026-07-27

Dashboard now splits crypto and stocks; old-model logs archived.

- Changed: `visualize_log.py` now produces a 5-panel dashboard instead
  of 3 - the whole-account net gain/loss panel is unchanged, but
  cumulative realized P&L and win/loss-per-ticker are each now two
  side-by-side panels (crypto, stocks) instead of one panel blending
  both together. Crypto runs `day_trading`, stocks run `ml_filtered`/
  `rule_based` - two strategies with nothing in common, so a shared line
  or bar chart said less than two separate ones do. Extracted the panel
  logic into `plot_cumulative_pnl()`/`plot_win_loss()`, called once per
  asset class, instead of duplicating it.
- Archived: `logs/trade_log.csv` (3 rows, all from the pre-0.7.0 crypto
  config) moved to `logs/trade_log_archive_pre_2026-07-27.csv` and
  started fresh - same reasoning as the 2026-07-25 rewrite, a new era
  of trades under a materially different live configuration deserves a
  clean log, with the old one kept, not deleted. `logs/equity_log.csv`
  was deliberately NOT archived - account equity is a continuous truth
  regardless of which strategy was live when, unlike a trade log that's
  meaningfully tied to "what rule made this decision."
- Archived: `results/trade_dashboard.png` (the old 3-panel design, still
  showing the pre-pause stock position and pre-0.7.0 crypto trades)
  moved to `results/trade_dashboard_archive_pre_2026-07-27.png`; a fresh
  dashboard was regenerated from the archived and new logs.
- Verified both the fresh (empty) log and the archived log render
  correctly through the new split panels before committing either.

## Version Richards 0.8.0 - 2026-07-27

Stock automation paused; `optimize.py`/`walk_forward.py` can now
validate the stock side too.

- Paused: the cron-job.org jobs driving `paper-trade-stocks.yml` and
  `retrain-stock-model.yml` were paused, and the open QQQ position was
  closed manually on Alpaca. Cause: the account was carrying an
  unmanaged ~$33k QQQ position (about a third of its value) from an
  order that silently filled sometime after being submitted outside
  market hours - never logged, because `live_trade.py` only records a
  trade at the moment a run makes a fresh decision, not when an old
  pending order quietly clears later on its own. Investigating that
  also surfaced a real gap: unlike crypto, `paper-trade-stocks.yml`
  never had `--max-notional` or `--daily-loss-limit` wired in at all -
  nothing was capping how large a single stock position could grow.
  Crypto's cash, positions, and forward-test history under 0.7.0 are
  completely untouched by any of this - separate account activity, same
  underlying Alpaca account. `paper-trade-stocks.yml` itself is
  unmodified and can resume whenever the cron-job.org jobs are unpaused.
- Added: `optimize.py` and `walk_forward.py` both gained `--strategy
  {day_trading, rule_based}` (default `day_trading`, unchanged
  behavior). `rule_based` validates the dip/recovery-exit shape
  `ml_filtered` (the live stock strategy) is actually built on - a
  different parameter shape than crypto's dip/profit-target/stop-loss,
  which the live stock workflow's `--dip-threshold -0.03` was never
  actually validated against, just picked. No Alpaca data work needed
  for this - stocks run on daily bars, and Yahoo's daily history is
  already decades deep for SPY/AAPL/QQQ.
- Added: `position_for_params()` in `src/strategies.py` - the one place
  both scripts now get "which strategy takes which parameters" from,
  instead of each keeping its own copy of that mapping (the same reason
  `day_trading_decision` was factored out in 0.5.0).
- Added: 3 new tests in `tests/test_strategies.py` covering
  `position_for_params()`'s dispatch for both strategies plus the
  unknown-strategy error case.
- Read-only research-tooling change for the `--strategy` addition; no
  code change to live crypto trading. Stopping stock automation is a
  separate, external decision (a cron-job.org toggle, plus any manual
  position cleanup on Alpaca's own dashboard) - not a code change,
  `paper-trade-stocks.yml` itself is untouched either way and can resume
  the same way it was ever running.

## Version Richards 0.7.3 - 2026-07-27

- Updated README's opening framing: it stated flatly that the honest
  answer to "does this beat buy-and-hold" was no. As of 0.7.0 that's no
  longer the whole story - reworded to say a validated configuration may
  have found something real, meaningfully de-risked but not yet a proven
  steady edge (same phrase already used in "Current live status,"
  CHANGELOG 0.7.0, and both `docs/RISK.md`/`docs/RESEARCH.md` -
  consistent terminology throughout now), and is now running live
  specifically to gather forward evidence rather than trust the backtest
  alone. Still points to "Current live status" for the full picture and
  caveats, and still ties "real money" to real trade evidence, not
  backtested numbers. Documentation-only; no code or live-trading
  behavior changed.

## Version Richards 0.7.2 - 2026-07-27

Full sweep: comments, docs, and stale-reference check across everything
touched since 0.6.0.

- Fixed: `evaluate_combo()` in `optimize.py` was missing a docstring -
  every other function in the file has one.
- Fixed: `get_price_data_smart()` (`src/data.py`) silently fell through
  to Yahoo with no explanation when Alpaca returned too few bars for a
  range - the exception path already printed a reason, this one didn't.
  Now both do.
- Fixed: README's file tree still described `src/data.py` as
  "Yahoo Finance, with synthetic fallback" only, and `results/` didn't
  mention `walk_forward.csv` or either chart PNG - both now match what's
  actually there.
- Fixed: the `1.0.0` requirements list at the top of this file still said
  walk-forward validation across multiple periods hadn't happened at
  all - it has now, once, as of 0.7.0. Reworded to say what's actually
  been done (one real round) versus what's still missing (repeating it,
  and explicit trending/choppy regime coverage).
- Fixed: `docs/RISK.md`'s pre-real-money checklist described
  walk-forward validation as a pending, ML-flavored idea (retrain on a
  rolling window) - `walk_forward.py` does something both simpler and
  already real (fixed-rule testing across sequential windows) and has
  now actually been used once; the checklist item now says so.
- No other bugs found; everything else (all doc cross-references,
  markdown links, image paths) re-verified clean.

## Version Richards 0.7.1 - 2026-07-27

- Added: `results/param_sweep_overview.png` and
  `results/walk_forward_winner.png` - rendered charts of the 0.7.0
  evidence CSVs, generated straight from `results/param_sweep.csv` and
  `results/walk_forward.csv` (not hand-edited), embedded in README's
  "Current live status" and `docs/RESEARCH.md`'s worked example. The
  scatter plot makes the "trading less often did better" pattern visible
  at a glance; the small-multiples grid makes clear where the 0.7.0
  combo's gains are concentrated (two specific calendar windows across
  several coins), the same caveat already in the 0.7.0 writeup, now
  visible instead of just described.
- Documentation-only; no code or live-trading behavior changed.

## Version Richards 0.7.0 - 2026-07-27

**Live crypto trading rules changed** - the first threshold change since
0.5.0 backed by real validation evidence, not a guess.

- Changed: `.github/workflows/paper-trade-crypto.yml` now runs
  `day_trading` with **`--dip-threshold -0.04 --profit-target 0.01
  --stop-loss 0.05`**, replacing the prior `-0.01 / 0.01 / 0.03`. The
  old combo bought on any 1%+ dip, which fires constantly on 5-minute
  bars - a `walk_forward.py` run across a real year of Alpaca data (see
  below) found it losing money in 53 of 54 ticker/window combinations,
  often placing 100-1,000+ trades per ticker in a single ~2-month
  window at a real ~0.2-0.4% round-trip fee floor. The new -4% threshold
  only buys real, comparatively rare dips - the same backtest period
  saw just 4-52 trades per ticker over the full year - trading the fee
  drag away rather than fighting it. `--profit-target`/`--stop-loss`
  also widened (1%/5% vs 1%/3%) to give a genuine 4%+ dip room to bounce
  without an early stop-out. `--max-notional` ($2,000) and
  `--daily-loss-limit` (5%) are unchanged.
- Added: `results/param_sweep.csv` - the full 90-combination grid search
  (`optimize.py`, real Alpaca 5-minute data, 2025-08-01 to 2026-07-27)
  that surfaced this combo as the best average-return result, with its
  closest neighbors (same dip/profit, different stop) landing within a
  couple points of each other - the "not an isolated overfit spike"
  check `docs/RESEARCH.md` describes.
  `worst_ticker_return` on the top two rows is **positive** - every one
  of the 9 coins was profitable, not just the average.
- Added: `results/walk_forward.csv` - the walk-forward validation of
  this specific combo (`walk_forward.py`, same real data, split into 6
  sequential ~2-month windows). 49 of 54 ticker/window results were
  non-negative (vs. 1 of 54 for the old combo) - a real, large
  improvement, though not an unqualified one: a large share of the
  total gain is concentrated in two specific windows
  (2025-09-30→2025-11-29 and 2026-01-28→2026-03-29) where several
  unrelated coins moved together, suggesting broad market-wide swings
  rather than an independent per-coin edge, and a couple of the winning
  windows (LTC, LINK) show large intra-window drawdowns (-37.7%, -31.8%)
  that the final window return doesn't show. Read as "meaningfully
  de-risked versus what was live before," not yet "a proven, steady
  edge" - see README's "Current live status" for the same caveat in
  context.
- Added: `walk_forward.py` now writes its own results to
  `results/walk_forward.csv` (`--out` to change the path), matching
  `optimize.py`'s existing `results/param_sweep.csv` output - every
  future validation run is now a durable, committable record instead of
  console output that scrolls away.

## Version Richards 0.6.3 - 2026-07-27

- Added: `optimize.py` now also pulls crypto history from Alpaca first
  via `get_price_data_smart()`, the same data path added to
  `walk_forward.py` in 0.6.2 - the parameter-sweep grid search can now
  run over a genuine year or more of real 5-minute crypto data instead
  of Yahoo Finance's ~60-day intraday cap. Each ticker's data-loading
  line now shows which source served it.
- Context: a `walk_forward.py` run against a full year of real Alpaca
  data (not yet possible before 0.6.2) found the live -1%/+1%/-3% combo
  losing money in the large majority of windows across nearly every
  coin, often with very high trade counts (100-300+ in a single
  ~2-month window) suggesting transaction-cost drag as a real
  contributor. `docs/RESEARCH.md` now documents re-running `optimize.py`
  over this same real data, searching toward less-frequent-trading
  combos, as the concrete next step - not yet done, and the live
  -1%/+1%/-3% thresholds are unchanged pending that.
- Read-only research-tooling change; no live crypto trading behavior
  affected.

## Version Richards 0.6.2 - 2026-07-27

- Added: `walk_forward.py` now pulls crypto history from **Alpaca first**
  instead of only Yahoo Finance, via a new `get_price_data_smart()` in
  `src/data.py`. Yahoo's intraday history is capped at roughly 60 days
  regardless of ticker, which made a real multi-window validation of the
  5-minute crypto strategy impossible past that; Alpaca (the actual
  venue this project trades against) isn't subject to that same
  free-tier retention limit, so a much longer `--start` can now work for
  crypto specifically. Falls back to Yahoo, then synthetic (skipped), if
  Alpaca has too little data for a given range - each window's output
  now shows exactly which source served it (`alpaca`/`yahoo`), so a
  fallback is visible, not silent.
- Added: `src/alpaca_data.py`'s `get_crypto_bars()` (live trading) was
  refactored to share its bar-fetching logic with the new
  `get_crypto_bars_range()` (historical/backtesting) instead of
  duplicating it - behavior-preserving for live trading, which still
  goes through the exact same staleness check as before.
- Added: `tests/test_data.py` - covers `get_price_data_smart()`'s
  routing (Alpaca-first for crypto, straight-to-Yahoo for stocks, and
  the fallback chain when Alpaca comes up short or unreachable).
- Read-only research-tooling change; no live crypto trading behavior
  affected - `live_trade.py`'s own price-fetching path is untouched.

## Version Richards 0.6.1 - 2026-07-27

Documentation restructure - no code or live-trading behavior changed.

- The README had grown to nearly 1,400 lines trying to serve three
  different audiences at once (portfolio reviewers, contributors,
  complete beginners), which made the important information hard to
  find. Split it into a short overview README plus four focused docs:
  `docs/BEGINNER_GUIDE.md` (plain-English walkthrough + glossary),
  `docs/AUTOMATION.md` (GitHub Actions/cron-job.org setup, logs and
  dashboard), `docs/RISK.md` (risk controls, real-money requirements),
  `docs/RESEARCH.md` (backtesting, strategies/ML detail, `optimize.py`,
  `walk_forward.py`).
- "Current live status" now leads with a compact scorecard table
  instead of only prose.
- Removed the bug-fix narrative bullets and the embedded "Version
  history" section from the README - that content already existed,
  word-for-word in spirit, in `CHANGELOG.md`. Versions now live only in
  the changelog; the README keeps just the current version number at
  the top.
- Fixed stale `README.md`-section cross-references in `live_trade.py`,
  `train_stock_model.py`, `visualize_log.py`, and two workflow files to
  point at the new doc locations.

## Version Richards 0.6.0 - 2026-07-27

- Added: `walk_forward.py` - splits a date range into several
  sequential, non-overlapping windows and re-scores a fixed
  dip/profit/stop combination independently on each one, instead of the
  single train/test split `main.py`/`optimize.py` use. A combo that only
  looks good on one window can still be luck; this is the "walk-forward
  validation across multiple distinct, non-overlapping time periods"
  named above as a 1.0.0 requirement. Defaults to the exact parameters
  the live crypto workflow trades with, so it validates the strategy
  actually running, not a hypothetical one. Read-only research tool -
  no change to live crypto behavior, and the -1%/+1%/-3% thresholds
  themselves are untouched pending more real trade history.
- Added: `tests/test_walk_forward.py` - covers the window-splitting
  logic (sequential, non-overlapping, covers the full requested range).

## Version Richards 0.5.2 - 2026-07-27

Full codebase sweep (every `src/*.py` file, `live_trade.py`, `main.py`,
`optimize.py`, `train_stock_model.py`, `visualize_log.py`, all 4
workflow files, and every test) re-read line by line looking for bugs
and comment gaps.

- Fixed: `--max-notional 0` was silently treated the same as
  `--max-notional` not being passed at all, because `if args.max_notional:`
  treats 0 and None identically in Python - an explicit zero cap should
  mean "never buy," not "fall back to the uncapped per-ticker split."
  Extracted into a small, directly-tested `compute_buy_budget()`
  function so this class of truthiness bug can't quietly return. Zero
  effect on current live behavior (the configured cap is $2,000, not 0).
- No other bugs found; everything else re-verified clean.

## Version Richards 0.5.1 - 2026-07-27

Bug found during a follow-up audit of 0.5.0's own changes.

- Fixed: `starting_cash = broker.get_cash()`, the circuit breaker's
  `broker.get_equity()` call, and the final per-run equity logging call
  had no error handling, unlike every per-ticker call - a transient
  Alpaca API failure on any of those three specific calls would still
  have crashed the entire run instead of failing gracefully and letting
  the next scheduled run retry. Wrapped in try/except, same pattern as
  the per-ticker isolation added in 0.4.0.
- Also brought `tests/fake_broker.py` and two other test files up to
  the same line-by-line comment standard as the rest of the codebase.

## Version Richards 0.5.0 - 2026-07-27

Test suite, a shared decision function, and two real risk controls -
the first two don't change crypto's behavior at all, the last two do.

- Added: `tests/` - 40 pytest tests covering RSI, label leakage, symbol
  resolution, backtest annualization, broker error handling, and the
  new shared decision logic below
- Added: `day_trading_decision()` in `src/strategies.py` - the one
  place the day-trading buy/sell/hold rule now lives, called by both
  the backtest (`dip_buy_profit_target`) and live trading (`decide()`)
  instead of each keeping its own copy that could quietly drift apart.
  Verified behavior-preserving against the old logic across 200,000
  randomized scenarios before going live - a pure refactor, not a
  strategy change
- Added: a daily-loss circuit breaker (`--daily-loss-limit`, default
  5%) - blocks new BUYs for the rest of the day once the account is
  down 5%+ from that day's starting equity; never blocks SELLs
- Added: `--max-notional` is now actually wired into the live crypto
  workflow (capped at $2,000/trade) - it existed as a flag before but
  was never passed by the workflow itself

## Version Richards 0.4.0 - 2026-07-27

Measurement and reliability audit - no changes to the actual crypto
trading rules (-1% dip / +1% profit / -3% stop are untouched).

- Fixed: RSI defaulted to neutral 50 during a pure uptrend instead of
  the correct 100, muting the strongest bullish signal (stock ML model only)
- Fixed: the ML model's training labels silently fabricated "didn't
  bounce" for rows with an incomplete lookahead window instead of
  excluding them (stock ML model only)
- Fixed: backtest annualized return/vol/Sharpe hardcoded 252 trading
  days/year regardless of the actual bar interval - wrong for intraday
  backtests (research tools only, not live trading)
- Fixed: `--cost-bps` help text called it a "round-trip cost" when it's
  actually charged on every position change (twice per round trip) -
  corrected the documentation, not the math, which was already right
- Fixed: broker position lookups treated every API error as "no
  position held," including real auth/rate-limit/server failures, not
  just genuine 404s
- Fixed: one ticker's API failure could crash the entire live run,
  silently skipping every other ticker scheduled that cycle
- Fixed: orders were logged as "placed" the instant they were
  submitted, not when actually filled - now polls for real fill
  confirmation and logs the actual fill price when available
- Added: `timeout-minutes` on all 4 GitHub Actions workflows
- Added: pinned `requirements.txt` to exact known-working versions
- Added: real-data fetch failures now print instead of failing silently

## Version Richards 0.3.0 - 2026-07-25

Bugs found from watching real live trades, not code review.

- Fixed a critical bug: crypto positions were invisible to the bot
  because Alpaca's client builds position-lookup URLs by plain string
  concatenation, and a symbol like `DOGE/USD` broke that path - the bot
  could never detect a crypto position it already held
- Fixed: BUY signals could stack a duplicate order on top of an
  already-open, unfilled order (found via two real stale QQQ orders)
- Fixed: `--dip-threshold` was silently ignored by `rule_based` and
  `ml_filtered`, always using a hardcoded 3% dip regardless of what was
  passed on the command line
- Reworked trade/equity logging into separate files with a manual
  `notes` flagging system, so an anomalous trade can be documented
  without deleting or hiding it
- Added the hourly-updating trade dashboard

## Version Richards 0.2.0 - 2026-07-25

- Added crypto support (BTC, ETH, SOL, DOGE, LTC, and more)
- Added GitHub Actions workflows for always-on automated paper trading,
  with an external scheduler (cron-job.org) working around GitHub's own
  unreliable `schedule:` trigger
- Added the day-trading strategy (profit-target/stop-loss exits from
  actual entry price) used for live crypto trading
- Added the Bollinger Band breakout strategy (implemented, not deployed)
- Added `optimize.py` for multi-ticker parameter sweeps

## Version Richards 0.1.0 - 2026-07-24

- Initial backtest engine, five trading strategies, and the ML dip-filter
- Initial automated paper trading against Alpaca (stocks)
