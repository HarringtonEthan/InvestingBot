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

## Version Richards 0.26.0 - 2026-08-14

- **Fixed a real bug: "All Time" (and This Week/This Month) collapsed
  down to just today, making 2.5 weeks of real trade history disappear
  from every dashboard stat** - `find_account_relaunch()` identified
  "the account's most recent relaunch" as the latest row where it held
  100% cash (zero open positions), which is the correct signature for a
  genuine relaunch *except* that a fully-traded account also returns to
  100% cash constantly and normally, any time every open position
  happens to close out at once - completely unrelated to a relaunch.
  Today was the first time since the real 2026-07-28 relaunch that
  happened (the AAPL position that had been open finally sold), and the
  very next dashboard refresh mistook that ordinary moment for a fresh
  relaunch, floored every period's calendar boundary at it, and made
  the site (and the PNG dashboard, which reads the same
  `starting_value_usd`/`starting_value_asof_utc` fields) look like the
  account had just been reset - "today is day 1" - while the underlying
  CSV logs were never touched and stayed completely intact throughout.
  Fixed by only considering fully-cash rows *at or before the account's
  first-ever logged trade* as relaunch candidates - a genuine relaunch
  always happens before any trading resumes; an ordinary all-positions-
  closed moment during live trading always happens after. 2 new tests
  cover both the incident (today's exact data) and the original
  intended behavior unchanged.
- No CSV data was lost, corrupted, or reset at any point - this was
  purely a display/aggregation bug in how the dashboard's JSON was
  computed from the (always-intact) logs.

## Version Richards 0.25.0 - 2026-08-07

- **New `--position-fraction` flag in `live_trade.py`** - spend a fixed
  fraction of currently-available cash per BUY (e.g. `0.2` = 20% per
  trade) instead of the default even cash/N-tickers split.
  Scale-invariant on purpose: the same `0.2` means $50 trades on a $250
  account and ~$20k trades on the ~$100k paper account, so the exact
  config being rehearsed on paper carries unchanged to a
  differently-sized real account later. Validated at startup (must be
  in (0, 1]); `--max-notional` still ceilings the result; a fraction of
  *remaining* cash shrinks geometrically across consecutive buys and
  can never fully drain the account on its own. 4 new tests.
- **Both live workflows now pass `--position-fraction 0.20` and raise
  `--max-notional` 10000 -> 30000.** 0.20 was chosen to exactly
  rehearse the planned real-money setup ("$50 trades on a $250
  account"). The cap now sits above the ~$20k natural first buy and is
  purely a blast-radius limit again (why it exists at all - see the
  2026-07-28 incident), no longer the thing doing the sizing. This
  supersedes 0.24.0's interim $10k cap the same day, before any trade
  executed under it.
- **Incident note - 2026-08-06: GitHub Actions platform outage.** For
  much of the trading day, GitHub's own Actions infrastructure failed
  runs before any project code executed ("Failed to resolve action
  download info. Error: Service Unavailable" during the runner's Set up
  job step), and queued retriggers cancelled each other under the
  workflows' concurrency group. Trading, dashboard, and data-refresh
  runs were all affected. Not a bug in this project, no code change
  made or needed, and no logged data was corrupted - but Aug 6 has a
  gap in potential trades/equity points that would otherwise look like
  the bot went quiet on its own, so it's recorded here the same way the
  project's own incidents are.

## Version Richards 0.24.0 - 2026-08-07

- **Position sizing raised: `--max-notional` 2000 -> 10000 in both live
  workflows** (~2% -> ~10% of the ~$100k account per position). The
  $2,000 cap was a post-incident guardrail that ended up as the binding
  constraint on every single buy - with all 9 stock tickers triggered
  the account could never deploy more than ~18% of itself, muting the
  equity curve, drawdown, and % return stats to unreadability while
  ~82% of the account sat idle. `live_trade.py`'s per-run
  cash/N-tickers split (~$11k when fully cashed) is the actual sizing
  mechanism and remains unchanged; the cap goes back to being what it
  was meant to be - a blast-radius limit for a runaway workflow, above
  the natural split, not below it. The 5% daily-loss circuit breaker
  also becomes genuinely reachable at this size instead of decorative.
  Deliberately NOT removed entirely: the 2026-07-28 incident is why a
  hard per-order ceiling exists at all.
- Rationale note: sizing up scales dollar P&L and dollar losses
  identically (it is not more evidence that the strategy works - win
  rate and per-trade % remain the evidence), and paper fills have no
  market impact, so no backtest could distinguish $2k from $10k sizing.
  This is a risk-preference change, made because the account is paper
  and the goal is seeing the strategy at a meaningful allocation.
- README status table and docs/RISK.md updated to match.

## Version Richards 0.23.0 - 2026-07-31

- **Reorganized position/tracker cards into two clearly-labeled, clearly-
  colored zones** to fix a real point of confusion: a card could show a
  green (profitable) P&L line right next to a red sparkline or a red
  "vs 20-bar avg" reading, because those numbers measure genuinely
  different things (since-purchase gain vs. the strategy's own
  mean-reversion signal) that can legitimately disagree in sign - it
  just looked like a contradiction.
  - "Your Position" (Qty/Entry/Current/Value + the bold P&L line) stays
    win/loss green/red throughout, as before.
  - "Strategy Signal" (the card sparkline, and the "vs 20-bar avg"
    reading) is now always one neutral blue (new `--signal-accent` CSS
    var), under its own small uppercase label with a divider - never
    win/loss green/red, so it can never visually contradict the P&L
    above it. Applies to both `index.html`'s position/tracker cards and
    `charts.html`'s position cards.
- **Ticker Tracker cards now show the actual buy/sell threshold**, not
  just the raw "vs 20-bar avg" percentage: a not-yet-held ticker reads
  e.g. "-1.17% (buys at -1.50%)", a held one "-0.80% (sells at
  +2.00%)" - the same threshold annotation position cards already had,
  extended to every watched ticker so it's clear at a glance how close
  something is to actually triggering a trade. New `site_data.py`
  constants `RULE_BASED_DIP_THRESHOLD` (-1.5%, stocks) and
  `DAY_TRADING_DIP_THRESHOLD` (-4%, crypto), matching the live
  workflows' own `--dip-threshold` values; crypto has no sell-threshold
  equivalent since day_trading exits on profit-target/stop-loss against
  entry price, not an SMA20 recovery - already covered by its own P&L.
- Cache-busting bumped to `?v=0.23.0`.

## Version Richards 0.22.0 - 2026-07-31

- **Fixed the entry-line reference dash drawing across the entire chart**
  on ranges like 100D for recently-bought positions (XOM, AAPL). The
  chart maps a position's real entry timestamp to a point index in the
  currently-displayed range; when the entry is *more recent* than every
  point in that range (e.g. bought today, but the 100-day view's last
  daily bar is only as fresh as yesterday's close), `findIndex` returns
  `-1` - previously treated the same as "entry predates the whole
  chart," which draws the line across everything. That's backwards: the
  position wasn't held during any of what's currently plotted. Added a
  `line.suppress` flag so `referenceLinePlugin` omits the line (and its
  start-point dot) entirely in that case, while the legend chip still
  shows the real entry price/percentage as text.
- **Sticky header** on both pages - it now stays pinned while scrolling
  long content (the Trades tab, charts.html), with a subtle shadow that
  only appears once real content has scrolled underneath it. Fixing
  this surfaced a real cross-browser CSS bug: `overflow-x: hidden` had
  been set on *both* `html` and `body`, which makes `body` its own
  scrolling box distinct from the page's root scroller - `position:
  sticky` elements inside it then track `body`'s internal scroll offset
  instead of the visible page scroll, so they silently scroll away
  instead of sticking. Moved `overflow-x: hidden` onto `html` alone.
- **Back-to-top button** added to `index.html` (previously only on
  `charts.html`) - same fade-in-after-scrolling behavior, respects
  reduced-motion.
- **Press feedback** (`transform: scale(0.97)` on click, matching the
  existing convention on tab/segmented/ghost buttons) added to the main
  nav links, content tab buttons, and the light/dark theme toggle.
- Cache-busting bumped to `?v=0.22.0`.

## Version Richards 0.21.0 - 2026-07-31

- **The card sparkline now plots the rolling 20-bar/5-minute average
  over time**, not raw daily price - the same signal already shown as
  each card's own "vs 20-bar avg" text stat, so the line and the number
  next to it always tell the same story. Free where possible:
  `build_ticker_tracker`'s spark reuses the exact same 5-minute-bar
  fetch already made for that stat's own current reading (no second
  fetch); `build_positions_payload` now fetches 5-minute bars (same
  interval/lookback as `SMA_INDICATOR_BAR_INTERVAL`/`_LOOKBACK_DAYS`)
  instead of the daily bars it fetched before. `_sparkline_closes` now
  takes a plain Series (whatever per-bar values a caller wants
  downsampled) instead of an OHLC DataFrame, since it's no longer
  specifically about close prices.
- Updated tests for the new spark source (a steadily-rising input's
  rolling average is itself monotonically non-decreasing, unlike noisy
  raw price) and the tooltip text on both cards.
- Cache-busting bumped to `?v=0.21.0`.

## Version Richards 0.20.0 - 2026-07-31

- **Fixed: a real trade that filled was staying mislabeled "Submitted,
  Unconfirmed" forever.** `live_trade.py`'s `poll_for_fill()` only waits
  a few seconds for Alpaca to confirm a just-submitted order before
  giving up - reported by a user who checked Alpaca's own activity log
  and found two stock buys (AAPL, XOM) that genuinely filled, just
  roughly one to two minutes after being logged, well outside that
  short window. New `Broker.list_recent_filled_orders()` plus
  `site_data.py`'s `reconcile_unconfirmed_fills()`: with
  `--live-positions`, any `submitted_unconfirmed` row from the last 3
  days now gets checked against Alpaca's own real order history and
  corrected to `confirmed_fill` (with the real fill price, and the real
  realized P&L recomputed if it was a SELL) if a matching filled order
  actually exists. This corrects the DISPLAYED data only -
  `trade_log_*.csv` itself is never rewritten, so it stays exactly what
  `live_trade.py` observed at decision time; the correction lives only
  in `trades.json`/`trades_full.csv`, the same "enrich with live
  context, never rewrite history" pattern `positions.json`'s own
  `--live-positions` data already uses.
- **Live-updating "(2m ago)"** next to the "Last updated" timestamp on
  both pages, ticking on a 30s client-side interval (no refetch) - makes
  it obvious at a glance the page is actually current without needing to
  reload.
- **Clarified what the new card sparklines actually show** - they had no
  label at all and were genuinely ambiguous next to the "vs 100-day avg"
  text already on the same card. A hover tooltip (and `aria-label`) now
  says plainly: last ~45 days of daily closes, not since purchase, not a
  rolling average.
- 9 new tests (`reconcile_unconfirmed_fills`'s matching/tolerance/window
  logic and non-blocking failure handling, `Broker.
  list_recent_filled_orders`'s filled-only filtering) - 239 tests total,
  all passing.
- Cache-busting bumped to `?v=0.20.0`.

## Version Richards 0.19.0 - 2026-07-31

- **Count-up animation on the headline metric cards** - switching Today/
  This Week/This Month/All Time now animates each number from its
  previous value to the new real one (~650ms, eased) instead of an
  instant snap. Purely cosmetic: the number it lands on is always the
  same exact real value a snap would have shown, and it's skipped
  entirely under prefers-reduced-motion or on first paint (no counting
  up from zero on load, which would itself read as a fabricated
  intermediate value).
- **Mini sparklines on every position/tracker card** - `site_data.py`
  now publishes a small `spark` array (~20 sampled recent daily closes)
  per ticker in both `positions.json` and `ticker_tracker.json`, reusing
  data already being fetched for other fields wherever possible (the
  ticker tracker's spark comes from the same 100-day-average df already
  in memory, no second fetch) or a small dedicated 45-day fetch
  otherwise. Small enough to publish unconditionally, unlike
  `ticker_charts.json`'s full range data (why that file stays fetched
  on-demand). Reuses the exact same sparkline renderer the headline
  equity card already draws with.
- **A real Open Graph / Twitter Card social preview.** Both pages now
  carry `og:*`/`twitter:*` meta tags pointing at a new branded
  `assets/og-image.png` (1200x630, the account/brand mark plus the site's
  own tagline) - previously, sharing either page's link anywhere would
  have shown as bare, unbranded text.
- **One consistent accent color per strategy** (`rule_based`/
  `ml_filtered`/`day_trading`), reused everywhere a strategy name
  appears - Trade History's Strategy column, the trade detail modal,
  position/tracker cards, and the Strategies tab's own card border - so
  the eye learns to tell them apart across the whole site instead of
  reading every instance as plain undifferentiated text.
- **Scroll-linked parallax on the ambient background** - the existing
  cursor-parallax glow layers (`assets/background.js`) now also drift a
  little at a fraction of the page's own scroll speed, so the backdrop
  reads as sitting behind the content rather than pinned flat to the
  viewport. Applies on touch devices too, unlike the cursor parallax,
  since scrolling has nothing to do with pointer capability.
- **Hovering the headline Win Rate card** reveals the real win/loss
  count it's computed from (e.g. "3 wins · 1 loss") - the same
  `num_wins`/`num_losses` the stats grid below already shows as separate
  tiles, surfaced here too since the headline row alone otherwise gives
  no way to see "37% of *what*" without scrolling down.
- **A branded empty-state glyph** - the generic sparkline-and-dot icon
  shown on every "nothing here yet" panel (positions, ticker tracker,
  trade history, chart cards) is now a simplified version of the
  account's own robot-head-plus-rising-bars mark (`assets/logo.svg`),
  tying "nothing here yet" back to the brand instead of a generic icon.
- Also fixed a stray pre-rebrand "casino dashboard" reference left over
  in `site_data.py`'s own module docstring from before the InvestingBot
  rebrand (0.9-ish era) - purely a comment/documentation fix, no
  behavior change.
- 6 new tests (`_sparkline_closes`'s downsampling/empty-input behavior,
  `build_positions_payload`/`build_ticker_tracker`'s own spark-field
  wiring and per-ticker fetch-failure isolation) - 230 tests total, all
  passing. Verified end-to-end with Playwright in both themes: the
  count-up animation lands on the correct real number, the Win Rate
  hover tooltip shows the real win/loss breakdown, strategy pills render
  with the right color in the Trade History table and the Strategies
  tab's card border, the scroll-parallax offset applies without
  throwing, and the OG image renders correctly at 1200x630.
- Cache-busting bumped to `?v=0.19.0`.

## Version Richards 0.18.0 - 2026-07-31

- **Per-ticker "report card"** in the chart modal: opening any ticker's
  chart (Positions, Ticker Tracker, or a chart-card position) now shows
  its all-time real trade record - trade count, win rate, realized P&L -
  directly below the chart. New `site_data.py` function
  `build_ticker_performance()` groups the exact same confirmed-fill-sell
  rollup (`_bucket_summary`, already trusted for the by-strategy and
  stocks-vs-crypto numbers elsewhere on the site) by ticker instead, so
  this never risks disagreeing with any other win-rate/P&L number on the
  page. A ticker with no confirmed sells yet shows nothing (no
  fabricated "0% win rate" for a position that's never been closed).
- **`ticker_charts.json` is now genuinely lazy-loaded.** The file's
  fetch-on-first-click logic in `position-chart.js`'s `openModal()` was
  already correct, but a separate, redundant eager prefetch at page load
  was defeating it - every visitor was downloading the full 100KB+ file
  even if they never opened a single chart. That prefetch call is
  removed; the file now only downloads the first time someone actually
  opens a chart, and stays cached in memory for the rest of the page
  view after that.
- **"Download full CSV" link on Trade History.** The table itself still
  caps at 200 rows for page weight, but `site_data.py` now also writes
  `trades_full.csv` - every trade ever logged, uncapped, in the same row
  shape as `trades.json` (both now built from one shared
  `_trade_row_json()` helper, so there's one definition of "what a trade
  row looks like" instead of two that could drift). A plain `<a
  download>` link next to the filter box points at it - no new backend
  endpoint, just a static file already sitting in `site/data/`.
- **Light mode.** A sun/moon toggle in the header (new `assets/theme.js`)
  flips a `data-theme` attribute on `<html>`, stamped before first paint
  from localStorage or the OS's own `prefers-color-scheme` so there's no
  flash of the wrong theme on load. The whole site's styling was already
  built entirely on CSS custom properties, so most of it themes for free
  from one new `:root[data-theme="light"]` palette; the handful of
  places that bypassed the variables (the header bar, the grid overlay,
  a badge background, the table's zebra stripe) got explicit light-mode
  overrides. Chart.js's own text/gridline colors read the live theme too
  and redraw immediately on toggle via a new `ib:theme-changed` event -
  no reload needed, and a chart already open in the modal updates in
  place.
- 7 new tests (`build_ticker_performance`'s per-ticker grouping and
  confirmed-sells-only filtering, `_trade_row_json`'s column order and
  honest blank-field handling) - 224 tests total, all passing. Verified
  end-to-end with Playwright: `ticker_charts.json` is confirmed absent
  from every network request until a chart is actually opened, the
  report card renders real trade stats below an opened chart, the CSV
  link points at a real uncapped file, and the light/dark toggle
  persists across reloads and redraws an already-rendered Chart.js chart
  live on click (both verified with a real Chart.js instance, not just
  the color-selection logic).
- Cache-busting bumped to `?v=0.18.0`.

## Version Richards 0.17.0 - 2026-07-31

- **Trade History rows are now clickable** - opens a detail modal with
  every field this project's trade log actually records for that row
  (full mode/notes text, cost basis, whether the fill was confirmed,
  realized P&L), plus a plain-language description of that row's own
  strategy rule. Deliberately does NOT show "indicator values at
  decision time" (the exact SMA/dip % the bot saw when it traded) -
  live_trade.py's own trade log never records those (its own
  `TRADE_LOG_FIELDS` comment says outright that "notes" is only ever a
  fill-confirmation status string, never decision reasoning), so
  inventing that number here would be exactly the kind of fabrication
  this site otherwise never does. The modal says so explicitly instead
  of pretending to a richer log this project doesn't actually have yet.
- **A search box above Trade History** filters the already-loaded (max
  200-row) table client-side by ticker, strategy, side, asset class, or
  note text as you type - no page reload, no server round trip.
- **New "Strategies" tab**: `rule_based` vs. `ml_filtered` vs.
  `day_trading`, reactive to the same Today/Week/Month/All Time
  selector Overview already uses. The underlying data
  (`dashboard.json`'s `periods[period].by_strategy`) was already being
  computed server-side by `summarize_period` - it just had never been
  rendered anywhere until now, so this shipped with zero backend
  changes, "which strategy is actually carrying the account" answered
  from data that already existed.
- **New "Backtest vs. Live" tab**: each asset class's exact currently-
  live config's own real walk-forward validation (`results/
  walk_forward/walk_forward.csv` for crypto, `walk_forward_stocks_5m_
  best.csv` for stocks - the same files `results/walk_forward/README.md`
  already documents as backing "Current live status") shown next to
  this account's own real all-time trading numbers. New `site_data.py`
  function `build_strategy_backtest_comparison()` parses those already-
  committed CSVs (no Alpaca credentials or network access needed,
  unlike every other Alpaca-backed file this script writes) into a new
  `backtest_comparison.json`. Deliberately NOT a literal overlaid
  equity curve - no per-day backtest equity series exists anywhere to
  overlay against the live one, and fabricating one would break this
  site's own "nothing here is simulated after the fact" promise - this
  is instead a direct, honest stat comparison (win rate, avg return per
  window, trade count) using exactly the real numbers that exist. A
  window only counts toward the backtested win rate if the strategy
  actually traded in it - a zero-trade window means "no signal fired,"
  not "the strategy lost."
- **Richer empty states**: every "no data yet" panel (positions, ticker
  tracker, trade history, the two new tabs above) now shows a small
  inline-SVG sparkline glyph above the message - a `background-image`
  data: URI, so this adds zero extra network requests and stays exactly
  as fast as the plain text it replaces.
- **The chart modal's line now eases in on first draw** - a slightly
  longer, curved-easing animation the very first time a chart renders
  after opening the modal. Switching ranges afterward (1D/1W/1M/100D)
  drops straight back to a near-instant redraw, so flipping between
  ranges never feels like it's making anyone wait on an animation - the
  entrance flourish is a first-impression thing, not a tax on every
  click.
- 5 new tests (`build_strategy_backtest_comparison`'s win-rate-only-
  over-traded-windows logic, honest `None` win rate when nothing
  traded, missing-CSV and per-class-isolated failure handling) - 217
  tests total, all passing. Verified end-to-end with Playwright: the
  trade detail modal renders every real field correctly and states its
  own honesty caveat, the filter narrows 11 rows down to 1 exact match
  and shows a real "no matches" state for a nonsense query, the
  Strategies tab correctly shows real rule_based numbers for All Time
  and an honest "nothing yet" message for Today (genuinely different
  underlying data, not a bug), and the Backtest vs. Live tab renders
  real validation numbers (88% win rate / 42 traded windows for crypto,
  76% / 51 windows for stocks) next to the account's own real live
  figures for both asset classes.
- Cache-busting bumped to `?v=0.17.0`.

## Version Richards 0.16.10 - 2026-07-31

- **Removed the on-canvas text labels from every chart's dashed
  reference lines** - crowding the chart itself with "100-Day Avg"/
  "Entry" text made it harder to read, not easier. The lines (plus the
  small dot marking exactly where an entry line starts) are the only
  thing drawn on the canvas now; the persistent legend below the range
  buttons - already added last release - is the sole explanation of
  what each one means and its current value, and it's the only thing
  that needed to be.
- **Fixed the real bug behind "the card is green but the chart opens
  red"**: a held ticker's overall up/down verdict (the modal's border
  accent, fill color, and the Entry legend chip's own %) used to come
  from comparing the real entry price against whichever historical bar
  happened to be the *last point of the currently-selected range* - and
  the modal's default view is 100 Day (daily bars), whose last point is
  *yesterday's* close. A position sitting at a small live gain could
  easily have closed yesterday slightly under entry, so the card (live
  quote) read green while the modal (yesterday's bar) opened red -
  nothing was actually wrong, two different points in time were being
  compared. `build_ticker_charts` now also publishes
  `live_current_price`/`live_unrealized_plpc` straight from the
  position object (never derived from any of its own historical bars),
  and the modal's one overall verdict always reads from that when a
  ticker is held - the exact number its own card is colored by - on
  every range, not just the default. Per-point segment coloring along
  the line itself is unchanged (it's a different, legitimate "was I
  above or below entry back then" signal), and a small pulsing "live"
  dot now marks the Entry legend chip's % specifically, since it's the
  one figure on the chart that isn't only as fresh as the currently-
  selected range's last bar.
- 1 new test (`live_current_price`/`live_unrealized_plpc` pass through
  correctly, and are `None` for a not-held ticker where the concept
  doesn't apply) - 213 tests total, all passing. Verified end-to-end
  with Playwright by deliberately reproducing the reported scenario
  (every range's own historical bars ending just under entry while the
  live quote sits just above it): the card and the modal now agree -
  both green - on every one of the four ranges.
- Cache-busting bumped to `?v=0.16.10`.

## Version Richards 0.16.9 - 2026-07-31

- **Every card sitewide now opens the exact same chart experience** -
  a position card on the Positions tab, a position card on charts.html's
  own Positions panels, and a Ticker Tracker card all read the same
  ticker_charts.json and open the identical range-selectable (1 Day/
  1 Week/1 Month/100 Day) modal. Previously a position card opened a
  different, more limited modal (a fixed "since purchase" span, no range
  buttons) than a Ticker Tracker card for the same ticker - that whole
  second "position mode" is gone (`site_data.py`'s `build_position_
  price_histories`/`position_history.json` retired along with it), so
  there's now exactly one click-to-chart implementation instead of two
  that could drift apart.
- **Fixed a real bug behind the confusing "profitable position, red
  chart" reports** (e.g. a stock sitting at +0.14% whose chart still
  looked like it was underwater the entire time): the old position-mode
  modal approximated a held position's "entry" reference line from the
  first bar of its own fetched price history, not the position's real
  average entry price - a mismatch that could make a genuinely-
  profitable position's chart read red the whole time. The unified
  modal now always uses the real Alpaca `avg_entry_price` (already
  published per-ticker in `ticker_charts.json`), and colors the price
  line itself (and the modal's own trend accent) against that same real
  entry price when held - or the ticker's 100-day average when not -
  instead of whatever point happens to be first in the currently-
  selected range. A not-held ticker's chart now visibly agrees with its
  own card text ("+3.4% vs 100-day avg") instead of an unrelated
  "up/down since the left edge of this window" reading that changed
  depending on which range was open.
- **The entry reference line now starts exactly where the position was
  actually bought**, not at the left edge of whatever range is open.
  `build_ticker_charts` now also publishes `entry_utc`/
  `entry_is_estimated` per held ticker (reusing `position_entry_
  timestamp`, the same trade-log rule position cards' strategy label
  already relies on); the frontend maps that timestamp onto the
  currently-displayed range and clips the dashed line - plus a small
  dot marking the exact start - to begin there. A position held longer
  than the visible window still draws the line across the whole chart,
  honestly, rather than guessing.
- **Every dashed reference line now has a persistent, always-visible key**
  under the range buttons (not just a hover tooltip or small on-canvas
  text) - e.g. "▬ 100-Day Avg: $210.40 -1.95%" and "▬ Entry: $206.00
  +0.14%" - so what a line means, and its current value, is never a
  mystery. A held ticker's modal also now shows a "Held" badge plus
  "Bought $X on DATE" right under the title.
- Found and fixed the same root cause (Alpaca's slash-less crypto
  position symbol, e.g. "BTCUSD", never matching the trade log's own
  bare-ticker "BTC" column) in two more places it had been quietly
  breaking things: `build_positions_payload` was labeling every crypto
  position's strategy "unknown" instead of "day_trading", and
  `build_position_sma_indicators` referenced a symbol-conversion helper
  that no longer exists after this cleanup (see below) - both now
  convert via `_position_ticker` first, the same fix already applied to
  `build_ticker_tracker`/`build_ticker_charts` last release.
  `positions.json` also now publishes each position's bare `ticker`
  (e.g. "BTC") alongside Alpaca's own `symbol` ("BTCUSD"), so the
  frontend can key into `ticker_charts.json` without reimplementing
  that conversion in JS.
- On-canvas reference-line labels now sit on a solid backing so they
  stay legible over gridlines/data instead of floating bare text, and
  the price line itself now fills with a soft gradient down to
  transparent for a cleaner, more "at a glance" read - both purely
  visual, no behavior change.
- 15 tests removed (covered dead code deleted in this release:
  `_pick_bar_interval`, `_crypto_alpaca_symbol`, `build_position_
  price_histories`), 4 new tests added (the crypto strategy-attribution
  fix, `entry_utc`/`entry_is_estimated` for both stock and crypto
  positions) - 212 tests total, all passing. Verified end-to-end with
  Playwright: a held stock's modal correctly
  reads green/"+0.14%" end to end (card, legend, and trend accent all
  agree), its entry line visibly starts at the real purchase date on
  the 1-month/100-day views and correctly spans the full 1-day view
  (entry predates it), the exact same modal opens from charts.html's
  Positions panel, and a not-held ticker's segments now visibly track
  its 100-day average.
- Cache-busting bumped to `?v=0.16.9`.

## Version Richards 0.16.8 - 2026-07-31

- **Removed the duplicated Ticker Tracker panels from charts.html** - the
  dedicated Ticker Tracker tab on index.html is the one place the full
  watched universe (held or not) is meant to show; charts.html's
  Positions panels correctly stay limited to currently-held positions
  only. The real bug behind "still can't hit the tab" turned out to be
  that charts.html's nav bar never had a Ticker Tracker link at all -
  added `<a href="index.html#tracker">Ticker Tracker</a>` alongside the
  other section links.
- **Every Ticker Tracker card now shows its 20-bar (5-minute) average**,
  not just the existing 100-day one, whether the bot currently holds
  that ticker or not - `build_ticker_tracker()` runs a second, separate
  bars fetch and reuses `add_features()` from `src/features.py` so the
  number is bit-for-bit the same `pct_below_sma20`/`sma20` the live
  `rule_based`/`ml_filtered` sell rule itself computes, not a
  reimplementation. Fails independently of the 100-day metric - a
  ticker with too little 5-minute history still shows its 100-day
  average, and vice versa.
- **Ticker Tracker cards are now sorted alphabetically by ticker**,
  stocks and crypto each in their own group, instead of the incidental
  order of the `--ticker` CLI list the live workflows happen to use.
- **Fixed the missing dashed reference line on the 1 Day range** in the
  Ticker Tracker chart modal. Root cause: Chart.js auto-scales the
  y-axis to fit only the visible price series, so a short 1-day range
  often sits far from a longer-term reference value and silently clips
  the line out of the drawable area. `renderChart()` in
  `position-chart.js` now explicitly computes y-axis min/max to always
  include every active reference line (8% padding), across all four
  ranges.
- **Reference lines are now self-explanatory** - each dashed line draws
  its own on-canvas label ("100-Day Avg", "Entry") next to the line
  itself, in a distinct color, instead of only being describable via
  hover tooltip.
- **Currently-held tickers now show a second reference line at their
  real entry price** - pulled straight from the live Alpaca position's
  `avg_entry_price` (not re-derived from the trade log), via the same
  `_position_ticker()` matching `build_position_sma_indicators` already
  used. `currentReferenceLines` is now an array so any number of lines
  can be drawn/labeled at once; today that's up to two (100-day SMA,
  entry price).
- 5 new tests covering the 20-bar SMA (available, insufficient-history,
  and independent-of-100-day-failure cases) and the held/entry-price
  matching for both stock and crypto positions - 223 tests total, all
  passing. Verified end-to-end with Playwright: charts.html has zero
  `.tracker-card` elements left, the new nav link correctly routes to
  the tracker tab, cards render in alphabetical order with both
  averages, and the 1-day chart for a held ticker shows both labeled
  lines fully visible despite sitting well outside the 1-day price
  range.
- Cache-busting bumped to `?v=0.16.8`.

## Version Richards 0.16.7 - 2026-07-31

- **Every Ticker Tracker card is now clickable**, on both index.html and
  charts.html (which didn't have a Ticker Tracker section at all until
  this release - added one, matching how Positions already exists on
  both pages): opens a price chart with a 1 Day/1 Week/1 Month/100 Day
  range selector, defaulting to 100 Day, plus a dashed reference line at
  the ticker's current 100-day SMA (the same number the card's own text
  already shows). All four ranges are fetched server-side up front, so
  switching ranges in the modal is instant with no extra network
  request. Added the same hover glow every other card on the site
  already gets (green-tinted for a held/profitable ticker, red-tinted
  for held/at-a-loss, neutral for not-held), plus full keyboard access
  (Tab/Enter/Escape).
- `site/assets/position-chart.js` (the shared price-chart modal
  position cards already used) now serves both position cards and
  Ticker Tracker cards from one implementation instead of two - a
  `data-tracker="true"` attribute picks tracker mode (ticker_charts.json,
  range-selectable) vs. position mode (position_history.json, fixed
  "since purchase" span). Found and fixed a real bug in the process:
  switching ranges wasn't tearing down the previous Chart.js instance
  first, so a range switch silently kept showing the old range's data
  (fixed by having renderChart() always destroy any existing chart
  before drawing).
- New `site_data.py` function `build_ticker_charts()` fetches each of
  the four ranges per watched ticker at its own fixed bar interval (5m/
  15m/1h/1d) and window, publishing points plus each ticker's 100-day
  SMA to a new `ticker_charts.json`. Same best-effort, per-range-and-
  per-ticker-isolated contract as this file's other Alpaca-backed
  builders - one range or ticker failing never blocks the rest.
- 9 new tests for `build_ticker_charts` - 218 tests total, all passing.
  Verified with Playwright end-to-end on both pages: card hover glow,
  modal open/range-switch/close, correct chart data per range, honest
  empty state for a ticker with insufficient history, keyboard open,
  and confirmed no regression to the existing position-card "since
  purchase" flow (range selector correctly stays hidden there).
- Cache-busting bumped to `?v=0.16.7`.

## Version Richards 0.16.6 - 2026-07-30

- **Added a Ticker Tracker tab** to the Positions area of the dashboard:
  every ticker either live workflow watches - not just the ones
  currently held - split into Stocks and Crypto, each showing its last
  daily close, its trailing 100-day SMA, and how far apart those two
  are. A held ticker's card is outlined green (currently in profit) or
  red (currently at a loss) - the same signal a position card's own
  border already gives; a watched-but-not-held ticker gets a neutral
  grey outline instead of no outline at all, so "not held" reads as a
  deliberate state, not a rendering gap.
- New `site_data.py` function `build_ticker_tracker()` fetches its own
  daily-bar series per ticker (`WATCHED_STOCK_TICKERS`/
  `WATCHED_CRYPTO_TICKERS`, kept in sync by hand with the two live
  workflows' own `--ticker` lists) and computes each one's 100-day SMA -
  a longer, more standard trend window than the 20-bar/5-minute one the
  rule_based exit signal uses, since this is a general "how's this
  ticker doing" reading across the whole watched universe, not a
  strategy-specific one. Same best-effort, never-crashes, per-ticker-
  isolated contract as the other Alpaca-backed builders in this file.
  Written to a new `ticker_tracker.json`.
- **Fixed a real symbol-matching bug found while building this**:
  Alpaca's positions endpoint returns crypto symbols without the "/"
  (e.g. "BTCUSD"), but live_trade.py logs the bare ticker ("BTC") to
  the trade log - `build_ticker_tracker`'s "is this currently held"
  check needed the two forms reconciled to match a live crypto position
  back to its watched ticker at all, which the new `_position_ticker()`
  helper now does. (Note: this specific fix only covers the new
  ticker-tracker code path - `attribute_position_strategy` and
  `position_entry_timestamp` still key off a live position's raw Alpaca
  symbol elsewhere in this file, so a held crypto position's strategy
  label and "since entry" chart start date remain affected by the same
  underlying mismatch; flagged for a follow-up, not fixed here.)
- Cache-busting bumped to `?v=0.16.6`. 10 new tests (8 for
  `build_ticker_tracker`, 2 for `_position_ticker`) - 209 tests total,
  all passing. Verified with Playwright against synthetic fixture data
  covering every card state (held+profit, held+loss, not-held, and the
  honest "not enough history yet" state): all four render with the
  correct outline color/badge and no console errors.

## Version Richards 0.16.5 - 2026-07-30

- **Fixed trade-log spam from a repeated "not placed" signal**: a real
  (non-HOLD) BUY/SELL decision that keeps firing every single 5-minute
  run while its underlying condition holds - most visibly, a stock dip
  signal that stays true for hours purely because the market is closed
  overnight/weekends - used to add a fresh, permanently git-committed
  row to `trade_log*.csv` on every one of those runs, even though
  nothing about the situation had actually changed since the last one
  (e.g. AAPL logging a new "Not Placed" BUY row every 5 minutes all
  evening). `live_trade.py` now snapshots each ticker's most recently
  logged row once at the start of a run and skips logging a new
  not-placed row when it's identical to that snapshot (same ticker,
  action, and reason, still never actually placed) - the first
  occurrence of a new "not placed" state still gets logged, and logging
  resumes normally the moment anything actually changes (market opens,
  an order is really submitted, the reason changes). This applies to
  every not-placed cause the same way (market closed, circuit breaker
  active, insufficient cash, an order already open, no `--execute`
  dry run) - none of those get row-per-run treatment anymore. A
  submitted or confirmed-fill row is never deduped; those are always
  genuinely new events.
- New `load_last_logged_rows()`/`is_duplicate_not_placed()` in
  `live_trade.py`. 8 new tests cover both directly (missing log file,
  most-recent-row-per-ticker, and every reason two rows can legitimately
  differ) - 199 tests total, all passing.

## Version Richards 0.16.4 - 2026-07-30

- **Added a "vs 20-bar avg" reading to every rule_based/ml_filtered
  position card** (Positions tab on index.html, and both positions
  panels on charts.html), so it's visible at a glance how close a held
  stock position is to its actual sell trigger without needing to check
  GitHub Actions logs. `rule_based`/`ml_filtered` sell on a
  mean-reversion recovery vs. the position's own trailing 20-period SMA
  (`pct_below_sma20`, exactly the number `src/features.py`'s
  `add_features()` computes and `.github/workflows/paper-trade-stocks.yml`
  currently sells at `+2.00%` of) - not vs. entry price, so the existing
  unrealized-P&L row on the card was never the right number for these
  positions in the first place. `live_trade.py`'s `decide()` only ever
  computes this for the `day_trading` branch, never for
  `rule_based`/`ml_filtered`, which is exactly why the live stock
  workflow's own logs have never shown it either - this reproduces the
  number for the dashboard using the identical formula, independently of
  that gap.
- New `site_data.py` function `build_position_sma_indicators()` fetches
  its own short, recent window of 5-minute bars ending right now (not
  from the position's entry date, unlike the existing "price since
  purchase" history) for each currently-open rule_based/ml_filtered
  position, so a just-opened position still gets a legitimate trailing
  SMA reading instead of an artificially-short one. day_trading (crypto)
  positions are skipped entirely - their existing unrealized gain/loss
  vs. entry is already the number that strategy's sell rule actually
  checks, so a second reading would be redundant. Same best-effort,
  never-crashes, per-symbol-isolated contract as
  `build_position_price_histories`: one ticker's bars being unfetchable,
  or not having 20 bars of trailing history yet, is recorded as that
  symbol's own honest "unavailable" state and never blocks another
  position's card. Written to a new `position_indicators.json`.
- Cache-busting bumped to `?v=0.16.4`. 9 new tests cover
  `build_position_sma_indicators` (not-requested/error/no-positions,
  day_trading skipped, rule_based and ml_filtered both included, crypto
  symbol conversion, insufficient-history honesty, per-symbol failure
  isolation) - 191 tests total, all passing. Verified with Playwright
  against synthetic fixture data on both pages: the new row renders with
  the correct sign color and "sells at +2.00%" label for a rule_based
  stock position, and is correctly absent for a day_trading crypto
  position.

## Version Richards 0.16.3 - 2026-07-30

- **Fixed the win/loss-per-ticker chart's tooltip always showing a green
  border**, regardless of whether the hovered ticker was actually a win
  or a loss: `externalTooltip()`'s bar-chart branch never set the shared
  `pointColor` variable the border reads, so it always fell through to
  the CSS default (green). It now inspects which dataset(s) are actually
  non-zero at the hovered ticker - a ticker that's pure losses (e.g.
  CAT) now shows a red border, pure wins show green, an all-unknown-P&L
  ticker shows gray, and a mixed ticker (some wins, some losses) is left
  at the neutral default rather than picking one color arbitrarily. The
  same fix also corrected the "Losses: N trades" row inside that
  tooltip, which read as green text before this (a trade *count* is
  never itself negative, so coloring it by sign always came out
  positive) - rows are now colored by which dataset they belong to,
  matching the bars and legend.
- **Fixed "Best Trade" and "Worst Trade" both naming the same losing
  trade** on a day with only losses (e.g. a single CAT loss showing up
  as both the "best" and "worst" trade of the day, which reads as if
  something good happened when nothing did). `best_trade` is now only
  populated from trades with a real gain; `worst_trade` only from trades
  with a real loss (or breakeven) - each field now only ever appears
  when there's something real behind it, showing "—" otherwise. The
  mirror case (an all-winning day showing one win as "Worst Trade") is
  fixed the same way.
- Cache-busting bumped to `?v=0.16.3`. Two new tests cover the all-loss
  and all-win single-trade cases directly; one existing test's
  expectation was corrected to match the fixed (not the buggy) behavior.
  182 tests total, all passing. Verified with Playwright against
  synthetic fixture data reproducing both reported bugs exactly (a
  single CAT loss): confirmed the tooltip border and row text render
  red, and confirmed "Best Trade" shows "—" while "Worst Trade" shows
  the real CAT loss.

## Version Richards 0.16.2 - 2026-07-30

- **Fixed a real layout bug in the header brand**: `.brand` is an
  `inline-flex` container with a `gap` between its children - wrapping
  "Bot" in its own `<span>` (to color it, in 0.16.0) meant the flexbox
  gap started applying *between* the plain text "Investing" and that
  span too, rendering as "Investing Bot" with an unintended space. Fixed
  by wrapping the whole "InvestingBot" label in one `<span
  class="brand-text">`, so the flex container only ever sees two
  children (the logo image and the text block) - "Bot" stays green,
  the gap goes back to being only between the logo and the text.
- A few more small touches:
  - Metric cards now carry the same trend-colored top border language
    position cards already use (green/red border-top when that card's
    own value is positive/negative, via a `:has()` selector - no JS
    changes needed), tying the headline row's visual language to the
    rest of the page.
  - Positions/trade-history empty states get a deliberately-styled
    dashed-border placeholder instead of plain unstyled text.
  - A green accent underline on the trade table's header row.
- Cache-busting bumped to `?v=0.16.2`. Verified with Playwright: brand
  text content confirmed as one unbroken "InvestingBot" string, metric
  card border colors confirmed programmatically against real rendered
  values, full pytest suite (180 tests, unaffected) still passes.

## Version Richards 0.16.1 - 2026-07-30

- **Fixed unreadable black legend text** on the account performance
  chart ("Net gain/loss vs. $X baseline") and both win/loss bar charts
  ("Wins"/"Losses") - the `generateLabels` override added in 0.16.0 to
  fix the legend swatch's mismatched outline returned label objects
  without a `fontColor`, so Chart.js fell through to the canvas
  context's own default fill color (black) for the text instead of this
  theme's actual legend color. Every legend now explicitly carries the
  theme's grey (`#9aa5a0`), matching the rest of the page.
- Three more small aesthetic touches:
  - Chart.js's own default font (a generic sans-serif) is now set
    globally to match the site's actual typeface (Inter), so chart text
    reads consistently with the rest of the page instead of looking like
    a pasted-in widget.
  - A faint dashed reference line at the entry price on each position's
    "since purchase" chart - the level its whole framing is measured
    against, made explicit the same way the account/cumulative-P&L
    charts already make their own $0 baseline explicit with a subtle
    reference line where the scale actually crosses it.
  - Subtle zebra striping on the trade history table's rows, for
    readability on longer trade lists.
- Cache-busting bumped to `?v=0.16.1`. Verified with Playwright: legend
  text color confirmed programmatically (`fontColor` on every rendered
  legend item) and visually via screenshot; full pytest suite (180
  tests, unaffected) still passes.

## Version Richards 0.16.0 - 2026-07-30

- **Added per-position "price since purchase" charts**, clickable from
  any open position card on both the Positions tab (index.html) and the
  Charts page's positions panels:
  - `site_data.py` now fetches real historical closing prices (Alpaca's
    existing `get_crypto_bars_range`/`get_stock_bars_range` - the same
    functions this project already uses for backtesting, no new data
    source) for every currently open position, from that position's own
    entry date through now, and publishes them to a new
    `site/data/position_history.json`. Entry date is derived from the
    trade log by the exact same rule `attribute_position_strategy`
    already uses (the most recent BUY with no later SELL), refactored
    into a shared `_last_open_buy_row` helper so the two can never
    disagree about which BUY a position traces back to. A position whose
    entry date can't be determined falls back to a 90-day lookback
    window rather than guessing or refusing to show anything; a
    per-symbol fetch failure is recorded as that symbol's own honest
    "unavailable" state and never blocks any other position's chart or
    the rest of the site's data. Bar interval (5m/15m/1h/4h/1d) is picked
    by how far back the range goes, and points are thinned to a bounded
    count so the file stays small regardless of interval. Only reachable
    with `--live-positions` (same opt-in flag positions.json already
    uses) and only imports alpaca-py then. 21 new tests, all against
    monkeypatched Alpaca calls - no real network access in CI.
  - New shared `site/assets/position-chart.js`, loaded by both pages:
    delegates clicks/Enter/Space on any `.position-card[data-symbol]`
    (added to both dashboard.js's and charts.js's own `positionCard()`
    templates) to open a modal with a Chart.js line chart of that
    symbol's real price history, colored green/red by net direction with
    the same per-segment coloring and custom crosshair/tooltip treatment
    the account performance chart already uses (reusing the exact same
    `#chart-tooltip` element/CSS, created on demand on pages that don't
    already declare one). Escape/backdrop-click/close-button dismiss it;
    focus returns to the card that opened it. Honest empty states for
    "feature not enabled this run," "fetch failed for this symbol," and
    "not enough points yet" - never a fabricated or interpolated chart.
- **Fixed the equity chart's legend swatch**: Chart.js's `usePointStyle`
  legend reads a dataset's *point* border/background styling, which this
  project's line datasets never set explicitly (only the line itself is
  styled) - Chart.js then fell back to its own default point border,
  which showed up as a mismatched outline around the legend's colored
  square that had nothing to do with the line's actual color. A
  `generateLabels` override now makes every chart's legend swatch a
  single solid box in the dataset's own color with no border at all - on
  the account performance chart this reads as a plain green or red
  square, matching the line and the account's actual current direction.
- **Colored "Bot" in the header brand** (`InvestingBot`) in the site's
  accent green, on both pages.
- A couple of small additional touches: a "View price history →" hint
  on every position card (discoverability for the feature above,
  brightens on hover/focus) and a floating back-to-top button on
  charts.html once scrolled past the fold.
- Cache-busting bumped to `?v=0.16.0`. Verified with Playwright
  (desktop/mobile, reduced-motion, keyboard-only interaction) against
  real mocked position/price data: opening/closing the modal via mouse
  and keyboard, focus return, both up and down positions, an
  intentionally-unavailable symbol's honest error state, and every
  pre-existing interaction (tabs, period filters, range control,
  deep links) all still behave identically. Full pytest suite: 180
  passing (159 before this version, 21 new).

## Version Richards 0.15.0 - 2026-07-30

- **Second visual-polish pass on the dashboard site**, again presentation-
  only: no displayed information, calculations, filtering, or trading
  functionality changed.
  - **Removed the panda intro splash** (`assets/intro.css`/`intro.js`
    deleted, markup/links removed from `index.html`) - the site's one
    remaining playful touch, now that the animated background carries
    the "this feels alive" job instead.
  - **Terminal-style tabular numerals:** a system monospace font stack
    (`--font-mono`, no webfont/network request) applied to every numeric
    value - metric cards, position-card figures, the trade table's
    Price/Qty/Realized columns, and chart tooltips - so digits align
    vertically the way they do on a real trading terminal.
  - **Account-value sparkline:** the headline "Account Value" card now
    draws a small inline SVG trend line from the same `equity.json`
    series charts.html already plots, filtered to whichever period is
    selected and colored by that period's real direction. Purely
    supplementary (`aria-hidden`, the exact number is always the text
    next to it) and draws nothing if fewer than 2 real points fall in
    the period.
  - **CSS-only loading skeletons:** `#stats-grid` and every
    `.position-cards` container shimmer while genuinely empty (a plain
    `:empty` selector - no JS state to manage, and it stops applying the
    instant real content, including a real empty-state message, is
    written in). The headline metric-row's "—" placeholders get the
    same shimmer via `body.is-loading`, cleared by `dashboard.js` the
    moment its first fetch settles either way.
  - **Live status pulse dot** next to "Last updated" on both pages -
    purely decorative (the adjacent timestamp is what's actually
    accurate), gentle and steady, never a jarring blink.
  - **Scroll-reveal on charts.html's section groups** (Account
    Performance/Crypto/Stocks fade and lift in as scrolled into view).
    Guarded so a missing or broken `charts.js` can never leave content
    invisible: the CSS that hides sections pre-reveal only applies
    behind a `body.reveal-ready` class that `charts.js` sets the instant
    it parses, so if that script 404s or throws, every section falls
    back to fully visible immediately. Falls back the same way under
    `prefers-reduced-motion` or if `IntersectionObserver` isn't
    supported.
  - **Themed scrollbar** on the horizontally-scrolling trade table.
  - Cache-busting bumped to `?v=0.15.0`. Verified with Playwright at
    desktop/mobile widths and with `prefers-reduced-motion` emulated:
    every tab, period filter, and deep link still behaves identically,
    no console errors from this project's own code, full pytest suite
    (159 tests, untouched) still passes.

## Version Richards 0.14.0 - 2026-07-30

- **Visual redesign of the dashboard site** (`site/index.html`, `site/charts.html`,
  `site/assets/styles.css`, new `site/assets/background.js`) - presentation-only,
  no displayed information, calculations, filtering, or trading-dashboard
  functionality changed. Every existing card, table, button, tab, and
  disclaimer is unchanged in content and location.
  - New lightweight canvas background (`assets/background.js`): sparse
    slowly-drifting particles, faint connecting lines between nearby ones,
    an occasional subtle rising/falling "ghost" market-line, and a small
    cursor-eased parallax on desktop. Single `<canvas id="bg-canvas">`,
    `pointer-events: none`, pauses while the tab is hidden, draws exactly
    one static frame under `prefers-reduced-motion` (no rAF loop at all),
    and scales particle count down on narrow/touch viewports.
  - CSS-only additions to `styles.css`: a faint fixed technical/grid
    overlay masked to fade out toward the edges, a second slow-drifting
    pair of colour glows layered behind the existing static ambient
    gradient, a soft radial glow seated behind the page heading, restrained
    glass-panel treatment (backdrop-blur + inner highlight) on metric/
    position/chart cards, richer hover/active/focus-visible states across
    nav links, tabs, segmented controls, and the ghost button, a smooth
    fade for the Overview/Positions/Trades panel switch, and a brief
    fade-in for cards and table rows as they render. All of it extends the
    existing `prefers-reduced-motion` override (already the site's
    established pattern) rather than adding a second mechanism.
  - Cache-busting `?v=` bumped to `0.14.0` across both HTML files so the
    new assets aren't served stale from GitHub Pages/browser caches.
  - Verified with Playwright at desktop/tablet/mobile widths and with
    `prefers-reduced-motion` emulated: every existing tab, period filter,
    range control, and deep link (`index.html#trades` etc.) still behaves
    identically, no console errors from any of this project's own code,
    and the full pytest suite (159 tests, untouched by this change) still
    passes.
  - To revert this redesign specifically, see commit `7702ebd` (the tip of
    this branch immediately before it) - the four files above are the only
    ones this change touched.

## Version Richards 0.13.7 - 2026-07-29

- **Fixed a real backfill:** XOM and DIS's two sells (2026-07-29) had
  their `avg_entry_price_usd` restored in `logs/trade_log_stocks.csv`
  from the matching BUY fills already in the same log (independently
  confirmed against Alpaca's own fill-level activity data) - realized
  P&L now shows the true, verified numbers (XOM +$64.73, DIS -$11.95,
  net +$52.78) instead of "unknown." `notes` deliberately left blank
  rather than annotated with the backfill rationale - visualize_log.py
  treats any non-empty `notes` as "flagged" (an unrepresentative-trade
  signal with its own hatched styling and excluded-trades line), which
  doesn't apply to a verified, complete backfill.
- **Fixed a real navigation bug:** the Overview/Positions/Trades links
  on charts.html all pointed at plain `index.html` with no anchor, so
  clicking any of them from the charts page always landed on index.html's
  default Overview tab first - a second click, now already on that page,
  was needed to actually reach the tab you wanted. Links now point to
  `index.html#overview`/`#positions`/`#trades`, and `dashboard.js` reads
  `location.hash` on load and switches to that tab immediately.
- **Fixed a real chart bug:** clicking a chart's legend item (e.g. "Net
  gain/loss vs. baseline") used Chart.js's default behavior of toggling
  that dataset's visibility - fine with several series, but on a
  single-series chart it hid the only line there was, leaving a
  technically-empty chart whose axis then autoscaled to an arbitrary,
  confusing range. `baseOptions()`'s legend now refuses to toggle off
  the last dataset still visible in any chart, so this can't happen
  regardless of how many series a given chart has.
- **Added a subtle, fixed ambient background** (soft green glow fading
  into the dark theme, several radial gradients, `background-attachment:
  fixed` so it reads as atmosphere rather than a banner that scrolls
  away) - no finance iconography, matching the existing brand palette.

## Version Richards 0.13.6 - 2026-07-29

Found via a user screenshot of the PNG dashboard: `visualize_log.py` had
the same missing-cost-basis gap as 0.13.3/0.13.4, but worse - it was
actively miscounting, not just hiding.

- **Fixed `plot_win_loss` silently counting an unknown-P&L sell as a
  loss.** `is_win = sells["realized_pnl_usd"] > 0` is `False` for `NaN`
  the same as any other comparison, so `~is_win` (everything not a win)
  quietly included every sell with no recorded cost basis too - both of
  today's stock sells (XOM, a real winner; DIS, a real loser) rendered
  as "2 losses, 0 wins." Unknown-P&L sells now get their own gray
  "Unknown P&L (no cost basis)" bar per ticker instead - still a real,
  visible bar, just honestly labeled.
- **Fixed `plot_cumulative_pnl` rendering a blank, oddly-scaled panel**
  when every sell in range had an unknown P&L (`cumsum()` over an
  all-`NaN` column plots nothing, leaving matplotlib's default
  arbitrary axis range with no explanation). Now shows the same "N
  confirmed sells recorded, but no cost basis" text the website
  already had, and still plots the running total for sells that DO have
  one, calling out how many were excluded.
- **charts.js's win/loss chart gets the same gray "Unknown" bar bucket**
  instead of falling back to text-only when every sell in range lacks a
  cost basis - the website's win/loss panel now looks like the PNG's
  again (real bars), rather than a wall of text where a chart used to be.
- Added `tests/test_visualize_log_win_loss.py` covering both fixes with
  a real matplotlib Axes (not just the plotting call not crashing) -
  checks actual bar heights and line data, not just "did it run."

## Version Richards 0.13.5 - 2026-07-29

- **Added cache-busting `?v=` query strings** to every stylesheet/script
  tag in `index.html`/`charts.html` (`styles.css`, `intro.css`,
  `dashboard.js`, `intro.js`, `charts.js`). None of them previously
  carried any version marker, so a browser (or GitHub Pages' CDN edge)
  could keep serving an old cached copy of one of these files for a
  while after a real fix had already been deployed - confirmed live:
  0.13.4's fix was already the deployed commit, but a user still saw the
  pre-fix behavior in their browser. Bump the `?v=` value on every
  future release that touches one of these files, the same way the
  version number itself already gets bumped.

## Version Richards 0.13.4 - 2026-07-29

Follow-up to 0.13.3: the charts page had the same missing-cost-basis gap
as its own separate bug, one layer up.

- **Fixed the Stocks Cumulative Realized P&L and Win/Loss charts
  claiming "No executed stock sell trades in this range"** even though
  2 real confirmed sells (XOM, DIS) happened - `confirmedSells()` in
  charts.js silently excluded any sell whose `realized_pnl_usd` was
  unknown (missing cost basis, same root cause as 0.13.3), so from the
  page's perspective those sells simply never existed. Now returns every
  confirmed sell regardless of known P&L; the chart still can't plot a
  dollar figure it doesn't have, but the empty-state and summary text
  now say "N confirmed sells recorded, but no cost basis to compute
  P&L" instead of falsely implying nothing happened.
- Also fixed a latent bug this exposed: JavaScript's `null <= 0` is
  `true`, so once unknown-P&L sells stopped being filtered out upstream,
  the win/loss chart would have silently counted them as losses. Both
  win/loss and cumulative P&L now explicitly filter to sells with a
  known `realized_pnl_usd` before doing any win/loss or sum arithmetic.

## Version Richards 0.13.3 - 2026-07-29

Fixed a real production crash: the scheduled "Update trade dashboard"
workflow started failing at its `Generate dashboard data (JSON)` step
(runs #136-138) the moment the account's first-ever confirmed SELL under
a non-`day_trading` strategy was logged.

- **Root cause, in `live_trade.py`:** `decide()` only fetched the
  position's real cost basis (`broker.get_position_avg_entry_price()`)
  inside the `day_trading`-only branch. Every other strategy - including
  `rule_based`, the one actually running live - fell through without
  ever fetching it, so a SELL under those strategies logged a blank
  `avg_entry_price_usd`. Today's XOM and DIS sells (2026-07-29, both
  `rule_based`) are the first sells this account has ever made, and both
  hit this gap. Fixed by moving the fetch above the strategy branch so
  it runs for any strategy whenever a position is currently held - it
  was always available from the broker, just never asked for outside
  `day_trading`.
- **Immediate crash, in `site_data.py`:** a SELL with no cost basis has
  a `NaN` `realized_pnl_usd`; `summarize_period()`'s best/worst-trade
  lookup called `idxmax()`/`idxmin()` directly on that column, which
  raises `ValueError: Encountered all NA values` on an all-`NaN` column
  instead of just skipping it - taking down the whole scheduled run
  (JSON generation, the PNG, and the Pages deploy all failed together).
  Now filters to rows with a computable P&L first: a sell with unknown
  P&L still counts toward `num_trades` (it's a real completed round
  trip) but is excluded from best/worst-trade ranking instead of
  crashing the page generation over it.
- The two already-logged sells will keep showing $0 realized P&L for
  today/this-week/etc. (an honest "unknown," not a real zero) since
  their cost basis was never recorded - the fix above only prevents this
  from happening to *future* sells.

## Version Richards 0.13.2 - 2026-07-29

More equity-chart coloring follow-ups, plus a new logo.

- **Tooltip border and swatch now match the hovered point's own sign,**
  not a fixed color. The custom tooltip's border was a hardcoded green
  (`var(--accent-dim)`) regardless of whether the point under the cursor
  was above or below the baseline; it now reads red or green from that
  exact point, same as the line/marker do.
- **Fixed the legend swatch not reliably tracking the account's
  direction.** The dataset had no explicit `backgroundColor` (only
  `borderColor` for the line's own stroke), so Chart.js's legend swatch
  fell back to its own default fill color instead of the green/red the
  rest of the chart uses. Set explicitly now.
- **New logo**: a robot head with an ascending price-chart antenna,
  replacing the plain accent-colored square in the header and the
  generic upward-arrow favicon (`site/assets/logo.svg`).

## Version Richards 0.13.1 - 2026-07-29

Follow-up fix to 0.13.0's equity-chart coloring, from real usage: the
line was using one fixed color for its entire length instead of tracking
the account's actual position at each point in time.

- **Fixed the equity line only reflecting its final point's sign.** The
  line color was computed once from the last recorded value, so a period
  that spent most of its time comfortably positive could still render
  entirely red just because it dipped negative right at the end. The
  line, and each point's own hover marker, now use Chart.js's per-segment
  coloring - green while above the $0 baseline, red while below it,
  switching right at each crossing - so the color always matches what
  the line is actually doing at that point in time, not just where it
  ended up.

## Version Richards 0.13.0 - 2026-07-29

Rebuilt the charts page to mirror the PNG dashboard's own layout, fixed a
real baseline-anchoring bug that let pre-relaunch history leak into
today/this-week/this-month/all-time, and gave the equity chart
direction-aware coloring.

- **Charts page now mirrors `visualize_log.py`'s PNG panel-for-panel.**
  Removed the Combined/Stocks/Crypto selector (a whole-account "combined"
  portfolio value split by asset class doesn't exist in the logs - both
  workflows log the same whole-account number, never a per-class
  balance - so overlaying three series that couldn't actually agree with
  each other was the reason the page looked broken). The chart set is
  now exactly the PNG's 7 panels: net account gain/loss (whole account),
  then crypto/stocks each get their own cumulative-realized-P&L and
  win/loss-per-ticker chart. Daily P&L / drawdown / strategy-comparison
  charts, which don't exist in the PNG either, were removed rather than
  left showing an empty state.
- **Range control now reads the server's own Today/This Week/This
  Month/All Time boundaries** from `dashboard.json` instead of rolling
  7/30-day windows, so the charts page can never disagree with the main
  dashboard about where a period starts.
- **Added a "Current Open Positions" panel under each asset class's
  charts**, reusing the same position-card component the main dashboard
  uses - fills what used to be a large empty area below the charts with
  real, relevant information instead of blank space.
- **Fixed a real bug: calendar period boundaries could reach past the
  account's most recent relaunch.** `site_data.py` now has
  `find_account_relaunch()`, which reads the account's own logged
  cash_usd/portfolio_value_usd columns for the most recent point they're
  exactly equal - the same signature every relaunch leaves behind (100%
  cash, zero open positions), not a guessed or hand-typed date. Every
  period's calendar start (midnight ET, the 1st of the month, ...) is
  now floored at that point, so "This Month" can no longer show a
  calendar-month boundary from before the account was last reset (e.g.
  showing July 1st as a start date when the account's current run
  actually began mid-afternoon on July 28th). The detected point is
  exposed as `account_relaunch` in `dashboard.json` for transparency.
  "Today" keeps normal midnight-ET semantics once enough time has passed
  that the calendar day no longer contains the relaunch - no special
  casing needed, the floor is simply a no-op past that point.
- **Equity chart line, hover point, card outline, and summary number now
  match the account's direction** - green if the period is up, red if
  down, the same red/green convention "Max Drawdown" already used on the
  main dashboard. Dropped the shaded area under the line entirely (line
  color only - a filled area under a line this active made the chart
  harder to read at a glance).

## Version Richards 0.12.1 - 2026-07-29

Made the charts genuinely interactive, and fixed a layout bug plus
several accuracy/labelling problems found while doing it.

- **Fixed the large empty area inside every chart card.** `.chart-empty-state`
  set `display: flex`, which beats the browser's own
  `[hidden] { display: none }` rule on specificity - so every *hidden*
  empty-state div still reserved its full min-height inside the card.
  That was the blank space below charts that had data. Hidden canvas
  wrappers had the same latent problem; both now have explicit hidden
  rules.
- **Custom interactive tooltips** on every chart, rendered through
  Chart.js's `external` handler into a styled element (near-black
  background, thin green border, white values, muted gray timestamp,
  green/red by sign) rather than Chart.js's default styling. Shows the
  date, exact ET time, portfolio value, gain/loss, period return and
  change from the previous recorded point, per series, with a colour
  swatch and name for each.
- **Vertical crosshair** snapped to the nearest real sample, larger
  hover point, and legend-aware tooltips (a series toggled off in the
  legend is excluded).
- **Range controls (Today / 7 Days / 30 Days / All Time)** and a
  **Combined / Stocks / Crypto** selector. Both re-drive the data,
  legend, tooltips, percentages and the accessible summary. 7 Days and
  30 Days are true rolling windows, not calendar week/month.
- **Drag-to-zoom with a reset button** on the main chart (desktop),
  implemented without adding any external plugin dependency. Zooming is
  entirely optional - the default view is correctly scaled on its own.
- **Mobile: tap-to-lock tooltips.** Fixed a real bug where the lock was
  applied on `click`; the synthetic click a browser fires after a tap
  arrived *after* Chart.js had already dispatched a hide, so tapping a
  point appeared to do nothing. Locking now happens on `touchstart`.
  Tooltips are clamped inside the viewport and all controls are >=40px.
- **Accessible text summary under every chart**, naming the range, the
  number of recorded samples, the first/last real timestamps and the
  values - each series' first/last value is index-paired with its *own*
  timestamp so a value can never be attributed to another series' time.
- **Accuracy work.** Series are aligned on a shared list of real sample
  timestamps; a series with no sample at a timestamp gets `null` (a real
  gap) and the tooltip reads "No recorded value" - never zero-filled,
  never interpolated. The client-side baseline now mirrors
  `site_data.py`'s reset/relaunch anchoring exactly (verified: both
  produce $99,751.68). Percentages smaller than a hundredth of a percent
  render with extra precision instead of a misleading "+0.00%".
- **Honest per-class labelling.** `equity_log_stocks.csv` and
  `equity_log_crypto.csv` both record the *whole account's* value (two
  workflows, one Alpaca account - verified against the logs), so a
  historical portfolio value split by asset class does not exist. It is
  not estimated: the per-class series show cumulative realized P&L from
  confirmed sell fills, which genuinely is per-class and timestamped,
  and its percentage is labelled "% of account baseline" rather than a
  "return". A footnote on the page states this.
- **Axis/label fixes.** The drawdown chart's crowded timestamps are
  capped at 4 ticks; axis labels switch between time-only (intraday) and
  date-only (multi-day); ticks drop cents while tooltips keep full
  precision; the main chart is much taller.
- Empty states now say *when* the most recent recorded sample was, so
  "Today" just after ET midnight (legitimately zero samples) points at
  real data instead of just saying nothing exists.

## Version Richards 0.12.0 - 2026-07-29

Full rebrand/redesign of the dashboard website away from the casino
theme, on request, plus a real bug fix found while investigating a
report that the content tabs "don't even work."

- **Found and fixed the actual tab bug.** `boot()` rendered positions
  and the trade history *before* attaching the tab click-listeners, with
  no error handling around either. If either render function threw on
  an unexpected data shape (verified by reproducing it with a
  deliberately malformed `positions.json`), the whole async `boot()`
  function aborted right there and the click-listeners for every tab -
  and the Today/Week/Month/All Time period pills - never got attached.
  Clicking any of them did nothing, with no visible error. Fixed two
  ways: listener attachment now happens first and unconditionally, and
  each render call is wrapped so one section's bad data can't take down
  the rest of the page's interactivity. Verified with real
  `page.click()` Playwright tests (not just programmatic state changes)
  against both good data and the reproduced broken-data case.
- **Removed the casino theme entirely** - gold/purple/neon palette,
  Bungee/Luckiest Guy fonts, slot machines, blackjack-style position
  cards, roulette-styled trade table, all casino terminology and emojis
  site-wide. Replaced with a plain dark theme (single green accent,
  Inter typeface), matching a reference design the request pointed to.
  The one thing kept exactly as it was: the panda-kiss intro splash.
- **Site renamed back to InvestingBot** everywhere - page titles, the
  nav brand, the favicon (a plain checkmark-trend mark, not an emoji).
- **Real navigation, not ad hoc buttons.** A proper top nav bar
  (Overview / Positions / Trades / Charts) on every page, with the
  current section clearly highlighted - `assets/casino-fx.js/css`
  deleted, replaced by `assets/intro.js/css` (panda splash only).
- **Removed the reset/relaunch caveat banner** from the UI on request.
  The underlying detection (`trade_log_reset_during_period` in
  `dashboard.json`) is untouched for anyone who wants it later - only
  the on-page banner is gone.
- Chart color palette (`charts.js`) renamed and restyled to match:
  green/red for gains/losses, blue for stocks, orange for crypto,
  neutral gray grid lines instead of gold.

## Version Richards 0.11.2 - 2026-07-29

Organization/readability pass on the casino dashboard website, from
real feedback after using 0.11.1: the page was one long undifferentiated
scroll, charts crammed in every timestamp, several charts went totally
blank with no data, and the charts-page dropdown was unreadable.

- **Split the main page into content tabs** (🃏 Stats / 🎴 Positions /
  🎡 Past Trades) instead of one long scroll of every section stacked
  on top of each other - a completely separate tab set from the
  existing Today/Week/Month/All-Time period pills, so the two never get
  confused with each other.
- **Moved the "View the Odds Board" charts link to right under the
  period tabs**, above the slot machines - visible on page load with no
  scrolling, instead of being the last thing at the bottom of the page.
- **Reduced chart x-axis clutter.** Every time-series chart used to
  label every single logged point (a new row every few minutes),
  producing dozens of overlapping timestamps. `maxTicksLimit`/`autoSkip`
  now cap it to a handful of evenly-spaced labels.
- **Every chart now explains itself when there's nothing to plot**,
  instead of rendering blank axes: Daily P&L and Drawdown say so when
  there isn't 2+ days of equity history yet; Strategy Comparison and
  the per-asset-class cumulative-P&L/win-loss charts say "no executed
  SELL trades yet" and additionally surface the relevant live unrealized
  P&L figure right there, mirroring what the PNG dashboard
  (`visualize_log.py`) already did for the same situation.
- **Fixed the unreadable chart-period dropdown.** Most browsers
  (especially mobile Safari) render a `<select>`'s popup option list
  with the OS's own white background regardless of the parent element's
  custom styling - cream-on-transparent text became cream-on-white.
  `<option>` elements now get an explicit dark color/light background so
  they're readable in the native popup, not just the closed control.
- **Added a blushing emoji next to the panda-kiss intro splash**, on
  request - kept the kiss, didn't touch anything else about it.
- Minor polish: chart cards no longer stretch to match a taller sibling
  in the same grid row (was leaving big empty gaps under short
  empty-state messages), and content-tab panels no longer double up on
  top margin from their first heading.

## Version Richards 0.11.1 - 2026-07-29

Follow-up fixes to the casino dashboard website (0.11.0), all from real
feedback after using it: the charts were unusably long and the page was
laggy, one card was unreadable, positions weren't visually grouped by
asset class, and the PNG dashboard had quietly stopped updating.

- **Fixed a real Chart.js sizing bug that made every chart grow
  unboundedly tall.** `maintainAspectRatio: false` inside a card `<div>`
  with no CSS-defined height let the canvas grow to fill whatever space
  was available - measured one chart rendering at 389x2320px in testing.
  Every canvas is now wrapped in `.chart-canvas-wrap`, a container with
  an explicit bounded height (`site/assets/styles.css`), which is what
  Chart.js's own docs call for with `maintainAspectRatio: false`. This
  was very likely the main cause of both "the charts are too long" and
  "the site is laggy" - a multi-thousand-pixel canvas is expensive to
  paint.
- **Moved the charts to their own page** (`site/charts.html` +
  `site/assets/charts.js`), reachable from a "View the Odds Board" link
  on the main dashboard. The main page no longer loads Chart.js or
  renders eight canvases at all - it only has the slot machines, open
  positions, and past trades now, which is both faster and matches the
  "condensed" main page that was asked for.
- **Removed the animated mobster/waiter lounge scene** added earlier in
  0.11.0 (`casino-fx.js`/`casino-fx.css`) - continuous CSS animations on
  a dozen-plus elements were a real contributor to the lag, and it was
  asked to be removed outright, not tuned down. Fireworks and the panda
  intro splash are unchanged (and fireworks are now 4 elements instead
  of 7, since a box-shadow burst animation is more expensive to repaint
  than a plain transform/opacity one).
- **Fixed the strategy label overlapping the dollar amount on stock
  position cards.** `.card-strategy` was absolutely positioned over the
  bottom of the card; it's now `.card-strategy-tag`, in normal document
  flow below the P&L line, plus available on hover via a `title`
  attribute.
- **Sectioned every part of the site by stocks vs. crypto**, using one
  consistent colour language everywhere (crypto = pink, stocks =
  purple): the open-positions table on the main page, and all three
  chart groupings on the new charts page ("Whole Account" / "Crypto" /
  "Stocks").
- **Restored `results/trade_dashboard.png` generation and commit-back**
  in `update-dashboard.yml`, alongside the website - `visualize_log.py`
  runs and the PNG gets committed the same way `paper-trade-*.yml`
  commit their logs, on request to keep both views updated rather than
  dropping the PNG when the website replaced it as the primary view.
  Safe against workflow loops for the same reason as always: this
  workflow is schedule/`workflow_dispatch`-triggered, never
  push-triggered, so a commit landing on the branch can't cause it to
  fire again.
- **Added a `trade_log_reset_during_period` flag** to `site_data.py`'s
  per-period summaries, surfaced as a caveat banner on the dashboard.
  `trade_log_*.csv` gets archived and restarted fresh on a same-day
  relaunch, but `equity_log_*.csv` never resets - so a period's
  equity-based Dollar P&L can straddle a relaunch while Realized P&L
  only counts trades since it, making the two numbers legitimately not
  add up. Rather than guess at the true reset boundary (which would
  reintroduce the same hardcoded-baseline problem 0.11.0 removed), this
  detects the mismatch honestly - whenever the earliest trade currently
  on record is newer than a period's own starting reference - and says
  so in the UI instead of presenting an unexplained gap.
- **Anchor a period's starting value to the relaunch itself, not stale
  pre-relaunch equity.** Follow-up to the flag above, same day: instead
  of only flagging the mismatch, `summarize_period()` now uses the last
  known equity right before the earliest trade currently on record as
  the starting value whenever that's more recent than the naive
  carried-forward figure - the full-cash reading a relaunch always
  leaves right before its first buy. Confirmed against today's real
  logs: "Today" now starts from $99,751.68 (the actual relaunch moment),
  not the stale pre-relaunch $99,787.08. Still not a hardcoded number -
  it's read straight off the equity log, so it keeps computing correctly
  on its own after future relaunches too.
- **Kept `results/trade_dashboard.png` in sync with that same anchor.**
  `visualize_log.py` has its own `--baseline`/`--baseline-since` flags
  (added back in v0.9.20 for this exact reset problem, but only ever
  filled in by hand - `100000` -> `99787.08` -> `99747.83` ->
  `99751.68`, one manual workflow edit per relaunch, every time someone
  noticed). `update-dashboard.yml` now reads `starting_value_usd` and
  the new `starting_value_asof_utc` field straight out of
  `site/data/dashboard.json` (generated one step earlier in the same
  run) and hands them to `visualize_log.py` as those same flags - one
  reset-detection implementation driving both the PNG and the website,
  no more hand-typed numbers on either one.

## Version Richards 0.11.0 - 2026-07-28

Replaced the static `results/trade_dashboard.png` (`visualize_log.py`) with
a real, deployed website - a tongue-in-cheek casino theme wrapped around
the exact same real numbers, published via GitHub Pages.

- **Added `site_data.py`** - the new script `update-dashboard.yml` runs
  instead of `visualize_log.py`. Reads the identical `logs/*.csv` files
  and (optionally, via `--live-positions`) the identical read-only Alpaca
  account/position query `visualize_log.py` already used - one source of
  truth, not a second copy that could drift - and writes four JSON files
  (`dashboard.json`, `positions.json`, `trades.json`, `equity.json`)
  instead of rendering a PNG.
  - **Removed the hardcoded `--baseline`/`--baseline-since` dollar
    amounts entirely.** Every period's starting value is now derived
    straight from `equity_log.csv`: the last known equity at or before
    that period's own calendar start (carried forward), falling back to
    the first value actually logged within the period if nothing earlier
    exists (e.g. right after an account reset) - flagged explicitly when
    that fallback happens, never silently presented as a true
    start-of-period balance. All-time starts from the very first row
    ever logged. This is the reason update-dashboard.yml no longer needs
    updating by hand every time the account resets.
  - **Today/This Week/This Month boundaries are computed in US Eastern
    Time** (`zoneinfo`, real IANA DST rules, not a fixed offset) and
    converted to UTC for filtering - all timestamps in the JSON/logs
    themselves stay UTC throughout.
  - **`classify_order_status()`** replaces the old "was a fill
    confirmed" ad-hoc check with three explicit, honestly-scoped
    categories the trade log can actually support: `confirmed_fill`,
    `submitted_unconfirmed`, `not_placed` - deliberately not a richer
    "canceled"/"rejected" set the logging doesn't actually distinguish
    today. Realized P&L, win/loss, and win-rate are computed only from
    `confirmed_fill` SELLs; unconfirmed and not-placed rows are tracked
    separately (`num_unconfirmed`/`num_not_placed`) and never silently
    folded into a "trade."
  - **`attribute_position_strategy()`** best-effort labels each open
    position with whichever strategy's BUY most recently opened it (no
    later SELL since) - Alpaca's own position data has no concept of
    "strategy" at all; this is purely this project's own trade-log
    bookkeeping, and returns `None` ("unknown") rather than guess when
    the log doesn't clearly support a better answer.
  - Added `Broker.get_buying_power()` (mirrors `get_cash()`/`get_equity()`)
    - the dashboard's "buying power" field.
- **Added `site/`** - the actual website: `index.html`, `assets/styles.css`,
  `assets/dashboard.js`, loading the JSON above via `fetch()`. Casino
  theme (neon marquee title, gold/velvet/purple styling, slot-machine
  reels that land on real numbers, blackjack-style position cards glowing
  green/red/gold by unrealized P&L, a roulette-styled trade ledger with
  confirmed/unconfirmed/not-placed status badges) built entirely in
  plain HTML/CSS/JS - no build step, no backend. Chart.js (CDN) renders
  the equity curve, daily P&L, drawdown, stocks-vs-crypto, strategy
  comparison, and win/loss charts. Respects `prefers-reduced-motion`
  (every animation gated off). Every `fetch()` is wrapped so a missing,
  empty, or malformed JSON file degrades to a clearly-labeled empty
  state instead of a broken page - verified directly (real headless-
  browser render, not just read through): with `dashboard.json` replaced
  by invalid text and every other data file deleted outright, the page
  still renders its header and a friendly "hasn't loaded yet" message,
  zero console errors.
- **`update-dashboard.yml` rewritten to deploy the website instead of
  committing a PNG - trigger and schedule completely unchanged**
  (`workflow_dispatch`/best-effort hourly `schedule:`, still fired the
  same way by cron-job.org). Now two jobs: `build` (checkout, run
  `site_data.py`, upload `site/` as a Pages artifact) and `deploy`
  (`actions/deploy-pages`). The generated JSON is never committed to the
  branch at all - it only ever exists inside that run's build artifact -
  which is also the loop-prevention mechanism the old PNG-committing
  version needed a git-conflict-retry loop for: there's nothing left to
  commit, so there's nothing that can trigger anything. `contents: write`
  dropped from this workflow's permissions entirely (replaced with
  `pages: write`/`id-token: write`); the trading/retrain workflows are
  untouched and still write their own logs exactly as before.
  - **One manual, one-time step this change can't do by itself**: the
    repository's Settings → Pages → Build and deployment → Source must
    be set to "GitHub Actions" (not a branch) before this workflow's
    first deploy will succeed - see README.md's "Local preview &
    hosting setup" section.
- **`visualize_log.py` archived, not deleted** - no longer called by
  any workflow, but still present and runnable locally for anyone who
  wants the old PNG output for a specific offline analysis.
  `results/trade_dashboard.png` is left in the repo as a historical
  artifact; nothing updates it anymore.
- **Added `site/assets/casino-fx.{css,js}`** - purely decorative extras,
  deliberately kept in their own files, separate from the real-data
  rendering in `dashboard.js`/`styles.css`, so it's obvious at a glance
  that none of it ever reads `dashboard.json`/`positions.json`/
  `trades.json`/`equity.json` or touches a real number: a CSS firework
  layer, an ambient "Back Room Lounge" scene (animal mobsters in fedoras
  idling, sipping drinks, smoking, one occasionally storming off and
  returning, a waiter doing rounds - all one looping CSS keyframe
  animation per character, no JS timers), and a giant-panda kiss splash
  on first load that dismisses itself (or on click). All of it is plain
  CSS/HTML - no new dependencies - and all of it is covered by the same
  `prefers-reduced-motion` override already in `styles.css`, verified
  directly: with reduced motion simulated, the panda splash is skipped
  entirely and the ambient scene sits frozen, confirmed via a real
  headless-browser render.
- New tests: `tests/test_site_data.py` (31 tests - order-status
  classification, ET daily/weekly/monthly boundaries, dedup, percentage
  return, realized-P&L-from-confirmed-fills-only, win/loss/best/worst,
  stocks-vs-crypto and strategy aggregation, missing/empty/malformed
  inputs, position-strategy attribution, missing-Alpaca-response
  handling) and one for `Broker.get_buying_power()` - 140 total passing.
  The website's own defensive-fetch behavior was verified with a real
  headless-browser render (Playwright/Chromium) against fixture data
  covering all three order statuses and both winning/losing/flat
  positions, plus a deliberately broken/missing-data run - screenshots
  reviewed directly, not just described.

## Version Richards 0.10.1 - 2026-07-28

Full codebase bug sweep after 0.10.0, requested specifically because that
fix touched the live stock decision path so recently. Found one real
regression it introduced; everything else checked out.

- **Fixed a regression 0.10.0 itself introduced: its date-bound fix
  silently broke the Yahoo-fallback tier for live stock decisions.**
  0.10.0 changed `decide()`'s stock branch to pass
  `dt.datetime.now(dt.timezone.utc)` (a full timestamp) as `end` to
  `get_price_data_smart()`, to stop the request from excluding today's
  session. That same string also gets handed to the Yahoo-fallback path
  if Alpaca fails - and `yfinance`'s own date parser
  (`yfinance.utils._parse_user_dt`) does
  `datetime.strptime(str(dt), '%Y-%m-%d')` on it, which raises
  `ValueError` on anything that isn't exactly a bare `"YYYY-MM-DD"`
  string. That exception doesn't crash the run - `get_price_data()`'s own
  broad except-and-fall-back-to-synthetic swallows it - so the practical
  effect was silently disabling the Yahoo fallback tier for live stock
  decisions specifically, not an obvious failure: any ticker that would
  have gotten a legitimate Yahoo Finance price if Alpaca ever failed
  would instead get treated as "only synthetic data available" and
  skipped for that run. Not a live-money-safety bug (nothing traded on
  synthetic data - it's still hard-blocked, same as always), but a real
  loss of resilience.
  - Confirmed directly:
    `datetime.strptime(dt.datetime.now(dt.timezone.utc).isoformat(), '%Y-%m-%d')`
    raises `ValueError: unconverted data remains: T19:24:45.513748+00:00`.
  - Fixed by passing **tomorrow's bare date** as `end` instead of a full
    timestamp - still exactly the `"YYYY-MM-DD"` shape both Alpaca
    (via `pd.Timestamp`) and Yahoo (via `yfinance`'s strptime) can
    parse, but strictly later than today's date, so midnight UTC of
    that bound is always still in the future relative to right now -
    the same fix as 0.10.0's, just without breaking Yahoo along the way.
  - `optimize.py`/`walk_forward.py`/`train_stock_model.py` were never
    affected - they either always passed bare dates already, or (for
    `train_stock_model.py`'s daily-bar default) never reach the branch
    that mattered.
  - Updated `tests/test_bars_freshness.py`'s regression test to check
    for exactly this shape (`test_decide_passes_tomorrows_bare_date_as_end`)
    and added a direct test that feeds `end` through the real
    `datetime.strptime` call yfinance itself makes
    (`test_end_is_a_bare_date_yfinance_can_parse`), so a regression like
    this would fail a test immediately instead of only being caught by
    chance during a manual sweep - 108 total passing.
- Reviewed every other source file (`src/broker.py`, `src/strategies.py`,
  `src/model.py`, `src/model_store.py`, `src/backtest.py`,
  `visualize_log.py`) - no further bugs found; comments were already
  current from prior sweeps.

## Version Richards 0.10.0 - 2026-07-28

Bumped the minor version instead of continuing the 0.9.x patch run (which
had reached 0.9.20 without the project ever having shipped a 1.x) - this
release also finally resolves the gap 0.9.20 could only flag, so it's a
real dividing line, not just a renumbering.

- **Found and fixed the actual root cause of the stale-rolling-average
  bug flagged as unresolved in 0.9.20.** It was never a genuine Alpaca
  data-freshness problem: `decide()`'s stock branch built the historical
  bars request's `end` bound from `dt.date.today().isoformat()` - a bare
  calendar date (e.g. `"2026-07-28"`), which `pd.Timestamp(..., tz="UTC")`
  turns into **midnight UTC of today**, hours *before* the moment any
  live run actually executes. That silently excluded the entire current
  trading session from every single stock fetch, every run, regardless
  of the real time - so the freshest bar available was always the
  previous session's last one, exactly matching the frozen
  "2026-07-27" timestamp seen in production for hours into the next
  day. Fixed by passing a real timestamp
  (`dt.datetime.now(dt.timezone.utc)`) instead of a bare date. This was
  a `live_trade.py`-only bug - crypto's live path (`get_crypto_bars()`)
  already built its request bound from `dt.datetime.now()`, never
  `date.today()`, which is why this was never observed on crypto.
- **Added `check_bars_freshness()` as a second, independent safety net**
  for the stock path: raises (skipping that ticker for the run) if the
  freshest bar returned is still older than the same per-interval
  thresholds `get_crypto_bars()` already enforces for crypto
  (`src/alpaca_data.py`'s `STALENESS_MINUTES`, now public so both paths
  share one set of numbers). This only runs at the live call site, not
  inside `get_price_data_smart()`/`get_stock_bars_range()` themselves -
  both are shared with `optimize.py`'s/`walk_forward.py`'s backtesting,
  which deliberately fetches an already-historical range and must never
  be rejected just for "looking old."
- **Removed `apply_live_price_override()` and `get_stock_latest_price()`
  from the live decision path** (0.9.18's fix) - patching only the bars
  series' last Close value never addressed the real problem (the whole
  series' `end` bound, not just its last cell) and is superseded by
  actually fixing the request bound plus the freshness check above.
  `get_price_data_smart()` itself is completely untouched, so live
  stock decisions are built from exactly the same Alpaca-first bars
  mechanism `optimize.py`/`walk_forward.py`'s validation already uses -
  a live decision was never meant to diverge from that methodology, and
  now it doesn't.
  - A design considered and rejected during this fix: a persistent,
    self-maintained live-price log that `decide()` would append to and
    read back from, replacing the bars fetch entirely. Rejected because
    it would have built the rolling average from a fundamentally
    different series (one live trade print per irregular cron tick)
    than the fixed-grid historical bars series walk-forward validation
    was actually tested against - exactly the kind of live/research
    mismatch this project has been trying to close, not widen.
  - **Every open stock position was manually sold and the paper account
    was reset again while this was being found.** New tracking
    baseline: **$99,751.68** (`update-dashboard.yml`'s `--baseline`
    and `--baseline-since`, updated from 99747.83 /
    2026-07-28T18:15:51+00:00 to 99751.68 / 2026-07-28T18:53:05+00:00).
    `logs/trade_log_stocks.csv` was archived to
    `logs/trade_log_stocks_archive_pre_2026-07-28_reset2.csv` and
    restarted empty; both equity logs got a fresh anchor row at the
    reset value.
  - Removed `tests/test_live_price_override.py` and
    `tests/test_alpaca_data.py`'s `get_stock_latest_price` tests
    (superseded); added `tests/test_bars_freshness.py`
    (`check_bars_freshness()`, plus a regression test confirming
    `decide()` passes a real timestamp - not a bare date - as `end`) -
    107 total passing.

## Version Richards 0.9.20 - 2026-07-28

- **Fixed the dashboard's net-gain/loss panel showing pre-reset history
  measured against the post-reset baseline.** After the 2026-07-28
  account reset, panel 1 still plotted the whole day's equity log -
  including everything from before $99,747.83 became the baseline -
  which read as a real multi-hour swing but was really just old equity
  held up against a number that didn't apply to it yet. Added
  `--baseline-since` (`visualize_log.py`'s new `filter_equity_since()`)
  to drop every row older than a given timestamp before plotting;
  `update-dashboard.yml` now passes `--baseline-since 2026-07-28T18:15:51+00:00`
  alongside `--baseline 99747.83`, so the chart only ever measures from
  the reset moment forward. New tests in `tests/test_baseline_since.py`
  - 106 total passing.
- **Flagged an unresolved gap in the 0.9.18 price-accuracy fix.**
  `apply_live_price_override()` only overwrites the bars series' last
  Close value - it does not touch that row's timestamp, and the "as of"
  timestamp logged by live trading runs is still the underlying bars
  fetch's own last index, which has continued showing 2026-07-27
  (Monday) in every run checked so far, both before and after the fix.
  That means the 20-period rolling average (`pct_below_sma20`, what the
  dip/exit decision is actually compared against) is very likely still
  being computed from 19 stale Monday bars plus the one corrected live
  price - not a genuine trailing 100 minutes of today's trading. The
  live *price* half of each decision is now confirmed accurate (see
  0.9.19's fill-price cross-check); the *rolling average it's compared
  against* has not been fixed and its correctness has not been verified.
  Not yet changed - under investigation.

## Version Richards 0.9.19 - 2026-07-28

- **Verified the 0.9.18 price-accuracy fix live, then re-enabled both
  cron-job.org schedulers.** A manually-triggered stock run placed real
  QQQ/XOM/CAT BUYs; cross-checked all three against three independent
  sources within a ~2-minute window - the live decision price, the
  actual confirmed fill price, and the dashboard's live position price
  (from a manually-triggered dashboard run) - and all three agreed
  within about 0.1% (XOM: $153.15 / $153.16 / $153.29; QQQ: $675.79 /
  $675.72 / $675.50; CAT: $831.60 / $831.84 / $830.72), a large
  improvement on the ~4% CAT gap that exposed the original bug. Both
  crypto and stocks are running again.

## Version Richards 0.9.18 - 2026-07-28

- **Fixed the actual root cause of the stock price-accuracy problem,
  and paused live trading while it was found.** 0.9.17's fix (switching
  stocks from Yahoo Finance to Alpaca's historical-bars feed) turned
  out to be insufficient on its own: within minutes of deploying it, a
  real QQQ BUY was placed at $679, while Alpaca's own live position
  pricing showed the true price around $679 but CAT's decision-time
  price ($873.14) differed from Alpaca's real-time position price
  ($838.50) by about 4% in the same 60-second window - confirmed by
  directly comparing a live trading run's console output against
  `results/trade_dashboard.png`'s position table, generated one second
  apart. Root cause: Alpaca's *free IEX historical-bars feed* (a single
  exchange, not the consolidated tape) can itself diverge meaningfully
  from Alpaca's own real-time pricing - a 5-minute bar's close only
  reflects whenever that bar's window happened to end, not literally
  "right now." Fixed by adding `get_stock_latest_price()`
  (`src/alpaca_data.py`, wraps Alpaca's latest-trade endpoint) and a new
  `apply_live_price_override()` (`live_trade.py`): the historical bars
  series is still used for rolling indicators (SMA/RSI tolerate a few
  minutes of lag fine - that's what "rolling" means), but the series'
  own last Close is now overwritten with a genuinely live trade price
  before those indicators are computed, so the actual dip/exit
  comparison is made against a live number. Crypto was unaffected
  throughout - its live path already had an explicit staleness check
  (rejects any bar older than 15 minutes) and isn't sourced from a
  single thin exchange the way stocks' free feed is; directly confirmed
  via production logs that crypto's decisions used bars only 5 minutes
  old throughout.
  - This does **not** invalidate the existing walk-forward validation:
    `optimize.py`/`walk_forward.py` already used this same Alpaca-first
    data source (`get_price_data_smart()`) for all intraday validation,
    crypto and stocks, before today - this fix only made *live* trading
    match what *research* already used, it didn't change the research
    itself. The newly-confirmed several-percent IEX divergence is a
    real reason to treat the stock walk-forward numbers' precision with
    more caution than before, since backtests assume a fill at the
    bars series' own price - but nothing about today's fix changed
    those numbers.
  - **Every open stock position was manually sold and the paper account
    was reset while this was being fixed.** New tracking baseline:
    **$99,747.83** (`update-dashboard.yml`'s `--baseline`, updated from
    99787.08). `logs/trade_log_stocks.csv` was archived to
    `logs/trade_log_stocks_archive_pre_2026-07-28_reset.csv` and
    restarted empty; both equity logs got a fresh anchor row at the
    reset value. Both crypto and stocks' cron-job.org schedulers were
    paused - re-enable manually once satisfied this fix is holding up.
  - New tests: `tests/test_alpaca_data.py` (`get_stock_latest_price`),
    `tests/test_live_price_override.py` (`apply_live_price_override`) -
    102 total passing.

## Version Richards 0.9.17 - 2026-07-28

- **Fixed live stock trading silently running on stale, day-old price
  data since before this project's first real stock trades.** Found by
  checking the console output of live production runs across a 2+ hour
  window (13:31 UTC, the exact run that placed the first real XOM/CAT/
  DIS BUYs, through 15:40 UTC): every single run reported the identical
  "as of 2026-07-27 15:55:00-04:00" bar - Monday's close, 5 minutes
  before market close - never once advancing to a fresh Tuesday bar,
  and never raising an error or tripping the existing synthetic-data
  check. Root cause: `live_trade.py`'s stock path called plain
  `get_price_data()` (Yahoo Finance only) - the exact same failure mode
  crypto already hit and was fixed for months ago (see
  `src/alpaca_data.py`'s docstring: "Yahoo's intraday crypto bars can
  silently go stale for hours without erroring"), but that fix was never
  applied to stocks. `optimize.py`/`walk_forward.py` (the tools that
  actually validated the live `rule_based` 5-minute strategy) already
  used Alpaca-first data via `get_price_data_smart()` - live trading was
  the one place still solely depending on Yahoo. Switched
  `live_trade.py`'s stock path to `get_price_data_smart()` too, so live
  trading now sees the same data source the strategy was validated
  against. Each run's console log now also prints which source served
  that decision (`alpaca`/`yahoo`/`synthetic`) specifically so a repeat
  of this would be visible immediately in the log, not discovered by
  chance again.
- Also fixed `docs/AUTOMATION.md`'s "Stock automation" section, which
  still said stocks were "Currently paused" - stale since stocks
  resumed; the main README's "Current live status" is the one kept
  accurate day to day.

## Version Richards 0.9.16 - 2026-07-28

- **Added a market-hours guard for stock orders.** Prompted by an
  external review of the repo that correctly identified this as the
  single most valuable gap: nothing in the code itself ever checked
  whether the stock market was actually open before submitting a BUY/
  SELL - the only thing preventing an out-of-hours order was "the
  external scheduler is configured to only call this during market
  hours," which is exactly the same class of failure (an external
  trigger misbehaving) that caused the real unmanaged-position incident
  earlier in this project's history (see 0.9.5). Added
  `Broker.is_market_open()` (wraps Alpaca's own `/clock` endpoint) and a
  new `stock_market_closed()` check in `live_trade.py`: any stock BUY/
  SELL is now skipped - logged with a clear note, never silently - if
  the market is confirmed closed at decision time, regardless of why the
  run happened to fire. Crypto is completely unaffected (it trades 24/7
  and never calls this at all). Fetched once per run, not per ticker,
  since every real workflow's `--ticker` list is always one asset class.
  New tests in `tests/test_market_clock.py` (6 tests, 97 total passing).
- **Fixed a stale, contradictory section in `docs/AUTOMATION.md`.** "Make
  it run automatically, on a schedule" still described the strategy as a
  once-a-day, near-market-close decision - true of an early version of
  this project, not the 5-minute `rule_based` strategy that's actually
  live now (correctly described later in the same document). Rewrote it
  to match current reality and pointed out explicitly that it's an
  alternative to GitHub Actions (what's actually deployed), not a
  description of it.
- Both changes came out of reviewing an external AI-generated repo audit
  (ChatGPT) against the actual code - most of its higher-risk suggestions
  (deterministic `client_order_id`s, a persistent order-reconciliation
  ledger, moving runtime state off git) were judged not worth the added
  engineering surface for this project's current scale and "let it
  gather real data" phase, but these two were cheap, safe (can only ever
  add a restriction, never loosen one), and directly closed off the
  actual incident class this project has already hit once.

## Version Richards 0.9.15 - 2026-07-28

- **Full codebase bug sweep.** Found and fixed two real, if narrow-scope,
  correctness bugs:
  - The daily-loss circuit breaker (`live_trade.py`'s
    `daily_loss_exceeded`/`_first_equity_today`) read only the currently-
    running workflow's own equity log to find "today's starting balance" -
    a side effect of splitting crypto/stocks into separate log files in
    0.9.9. Since both files record the SAME whole-account equity, this
    could miss an earlier "today" row logged by the other asset class's
    workflow a few minutes before this one first ran today, silently
    using a slightly-late (and already-lower) baseline instead of the
    account's true start of day. Fixed by threading an explicit
    `equity_log_paths` list through both functions; `main()` now passes
    every known equity log (`ALL_EQUITY_LOG_PATHS`), so the breaker
    always finds the true earliest "today" row across both files,
    regardless of which one this process itself writes to.
  - `src/data.py`'s `PERIODS_PER_YEAR_24_7` table was missing a `"4h"`
    entry, even though 4-hour bars are a real, documented crypto interval
    (`live_trade.py`/`src/alpaca_data.py`). A 4h crypto backtest via
    `periods_per_year()` silently fell through to the 252 stock-calendar
    fallback instead of a 24/7 count, understating how many bars occur in
    a year and skewing annualized return/vol/Sharpe for that interval
    only - total return and drawdown were unaffected. Added the missing
    entry (`365 * 24 // 4`).
  - Reviewed every other source file, all 5 workflow YAMLs, `.gitattributes`,
    and `requirements.txt` against actual imports - no further issues found.
  New tests: `tests/test_circuit_breaker.py::test_uses_earliest_row_across_both_asset_class_logs`,
  `tests/test_data.py::test_periods_per_year_4h_crypto_uses_24_7_calendar`.
- **README polish.** Fixed a stale "81 tests passing" reference (actually
  91 by now), added a short "What's next" note at the end of "Current
  live status" making explicit that this phase is about letting both
  configurations accumulate real closed trades, not further tuning -
  and verified every image/CSV link in the README actually resolves on
  disk.

## Version Richards 0.9.14 - 2026-07-28

- **Fixed the dashboard's account-total panel not reconciling with the
  new live unrealized-P&L numbers from 0.9.13.** Reported live: net
  account gain/loss showed -$9.44 while the stock P&L panel's live
  unrealized number showed -$18.87 with zero crypto held - looked like a
  bug, and the math confirmed why: panel 1 read the last row of the
  equity log (a snapshot from whenever the 5-minute trading cron last
  ran), while the live unrealized number was pulled from Alpaca at
  dashboard-generation time, several minutes later, after stock prices
  had moved further. Both numbers were individually correct, just
  computed at different instants. Fixed by having `--live-positions`
  also fetch the account's current live equity (same broker call, same
  moment as the positions pulled for the P&L panels) and append it to
  panel 1's timeline via the new `append_live_equity_point()` in
  `visualize_log.py`, so every number on the dashboard now describes the
  same instant.
- **Added a current-open-positions table per asset class.** Two new
  panels (crypto and stocks) list every currently-open position - symbol,
  price, qty, market value, unrealized P&L - the same shape Alpaca's own
  account dashboard shows, via the new `plot_positions_table()`. Only
  populated with `--live-positions`; without it, the panels say so
  rather than showing stale or fabricated numbers. Dashboard is now
  seven panels total. New tests in `tests/test_live_positions.py` cover
  the reconciliation logic and the positions table's sorting/formatting.

## Version Richards 0.9.13 - 2026-07-28

- **Added live unrealized P&L per asset class to the dashboard.** The
  crypto/stock P&L panels previously only showed *realized* P&L from
  closed (SELL) trades - an open position that's never been sold showed
  as "nothing happening" even while it was actively up or down real
  money. Added `Broker.get_all_positions()` (`src/broker.py`), which
  pulls every currently-open position from Alpaca and classifies each
  one crypto vs. stock using Alpaca's own `Position.asset_class` field
  (not re-derived from the symbol string - Alpaca's positions endpoint
  returns crypto symbols without a "/", e.g. "BTCUSD", which this
  project's own `resolve_symbol()` would not recognize as crypto).
  `visualize_log.py` gained a new `--live-positions` flag (needs
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY`) that sums each asset class's
  `unrealized_pl` and annotates the total directly on that class's P&L
  panel, alongside whatever realized-trade history is already there -
  read-only, never places an order. `update-dashboard.yml` now passes
  this flag on every scheduled run, so the dashboard always shows
  whether crypto or stocks is winning *right now*, not just whether
  their closed trades won historically. New tests in
  `tests/test_live_positions.py` cover the crypto/stock split logic
  directly (no live Alpaca connection needed).

## Version Richards 0.9.12 - 2026-07-28

- **Changed the dashboard's baseline from the original $100,000 funding
  amount to $99,787.08** (the account's real value at the start of
  today, 2026-07-28, before any of today's trades) - `update-dashboard.yml`
  now runs `visualize_log.py --baseline 99787.08`, so the "Net account
  gain/loss" panel reads as **today's P&L specifically**, not all-time
  P&L since funding. Both are valid readings of the same data; this is a
  deliberate choice of which one the dashboard shows by default now.
  Documented in `docs/AUTOMATION.md`, including that this baseline value
  needs to be updated again whenever "today" moves forward - otherwise
  the panel keeps measuring against an increasingly stale reference
  point instead of the current day.

## Version Richards 0.9.11 - 2026-07-28

- **Reorganized `results/` into `results/param_sweep/` and
  `results/walk_forward/` subfolders**, per feedback that the top level
  had gotten cluttered with grid-search/validation output. Only
  `trade_dashboard.png` (the one worth checking first) and
  `equity_curve.png` stay directly in `results/`. Added a `README.md` in
  each new subfolder explicitly labeling which specific file(s) back the
  currently ACTIVE live crypto/stock config versus which are
  explored-but-not-deployed candidates - `param_sweep.csv`/
  `param_sweep_overview.png`/`walk_forward.csv`/`walk_forward_winner.png`
  for crypto (day_trading -4%/+1%/-5%); `walk_forward_stocks_5m_best.csv`/
  `walk_forward_stocks_5m_best_candidate.png`/`walk_forward_stocks_summary.*`
  and the 5-minute grid-search overview chart for stocks (`rule_based`
  5m dip=-1.5%/exit=2.0%, the best of 8). `optimize.py`/`walk_forward.py`'s
  `--out` defaults updated to match; every reference in README/
  `docs/RESEARCH.md`/`docs/AUTOMATION.md` updated.
- **Seeded both split equity logs with one shared historical anchor
  row** (`2026-07-28T07:05:54Z, $99,787.08` - the last known real
  account value before today's stock trades, from the archived
  pre-split history) so the dashboard's whole-account timeline shows
  today's full picture from before market open, not just the last few
  minutes since the 0.9.9 split. Both `logs/equity_log_crypto.csv` and
  `logs/equity_log_stocks.csv` start with this identical real value -
  it's shared because account equity is one number regardless of which
  workflow happens to sample it, not two separate balances.
- **Fixed a real commit-authorship mistake**: while reproducing the
  0.9.8 git-conflict bug locally in a temporary `git worktree`, running
  `git config user.email/user.name` there silently changed the *main*
  repository's committer identity too (worktrees share the same
  `.git/config` unless told otherwise) - every commit from 0.9.8 through
  0.9.10 was authored as `t <t@t.com>` instead of the correct `Claude
  <noreply@anthropic.com>`. Content of those commits is unaffected; only
  the author label was wrong. Local override removed; commits from here
  on use the correct identity. Not rewriting the already-pushed history
  to relabel it - force-pushing on a branch with cron-job.org committing
  every 5 minutes isn't worth the risk for a cosmetic fix.

## Version Richards 0.9.10 - 2026-07-28

- **Trimmed the README's "Current live status" section** after feedback
  that it had become mostly history, not status: removed the QQQ
  incident writeup, the second stock incident writeup, the
  post-incident hardening writeup, and a stale 2026-07-27 results
  snapshot - all of it was already recorded in this changelog (0.8.0,
  0.9.5, 0.9.6, 0.9.8), just duplicated at length in the README too. The
  section now covers only what's actually true right now: which
  workflows are running, how they're triggered, the crypto/stock
  comparison table, what the test suite does and doesn't prove, and the
  evergreen strategy-validation summaries (with their charts) that
  explain why the current configuration was chosen - not the blow-by-
  blow story of how it got there.

## Version Richards 0.9.9 - 2026-07-28

- **Split crypto and stock logs into separate files entirely** -
  `logs/trade_log_crypto.csv`/`logs/equity_log_crypto.csv` and
  `logs/trade_log_stocks.csv`/`logs/equity_log_stocks.csv`, instead of
  one shared pair. This removes the shared-file class of git conflict
  altogether, on top of the 0.9.8 `.gitattributes` fix (which still
  covers any two processes that DO end up sharing a file, e.g. two
  overlapping runs of the same workflow, or a manual local run).
  `live_trade.py` gained `--log-suffix` (each workflow passes
  `_crypto`/`_stocks`); `visualize_log.py`'s `--equity-log`/`--trade-log`
  now accept multiple files and combine them into one timeline (default:
  both asset classes' files) - the whole-account panel still needs one
  combined view, since crypto and stocks share one real Alpaca account.
  2 new tests (`tests/test_log_suffix.py`).
- **Migrated existing log data**: `logs/trade_log.csv` (3 real stock
  rows, all already correctly attributed) became
  `logs/trade_log_stocks.csv` directly - no data lost. `logs/equity_log.csv`
  (85 mixed rows, not cleanly attributable per-row to a specific
  workflow after the fact) was archived whole to
  `logs/equity_log_archive_pre_2026-07-28_split.csv`; both
  `logs/equity_log_crypto.csv`/`logs/equity_log_stocks.csv` start fresh
  from here - same "start clean, archive the old, never delete"
  precedent as every prior log rebuild in this project.
- Updated `docs/AUTOMATION.md`/`docs/BEGINNER_GUIDE.md`/README's file
  tree for the new filenames.

## Version Richards 0.9.8 - 2026-07-28

- **Found and fixed the real cause of the "Commit trade log" failures**
  the 0.9.7 retry loop didn't actually fix. Reproduced locally: two
  workflows each appending one new row to the end of the same CSV
  (`logs/equity_log.csv`) produce a **deterministic** git rebase
  conflict, not a timing race - confirmed live when a stock run failed
  identically on all 5 of its retry attempts against the exact same
  conflict. Retrying the same rebase can never fix a real content
  conflict. Added `.gitattributes` with `merge=union` for
  `logs/trade_log.csv` and `logs/equity_log.csv` - verified locally this
  resolves the exact reproduced conflict cleanly, keeping both sides'
  rows. The 0.9.7 retry loop stays in all 4 workflows as a second layer,
  now correctly scoped to the genuine residual case (a plain
  non-fast-forward push rejection with no content conflict).
- **Removed `paper-trade-crypto.yml`'s native GitHub `schedule:`
  trigger** (`workflow_dispatch` only now), matching what 0.9.5 already
  did for stocks. cron-job.org already calls it reliably every 5
  minutes; the native schedule was a second, redundant trigger path -
  another source of the exact kind of concurrent-commit collision fixed
  above.
- **Corrected a wrong claim from 0.9.5/0.9.6: stocks were never actually
  paused.** Checking the GitHub Actions run history directly shows
  `workflow_dispatch` events on `paper-trade-stocks.yml` landing every 5
  minutes, continuously - cron-job.org calling it the whole time, not
  occasional manual clicks as previously assumed, and not paused despite
  what the README said. Nothing dangerous resulted (it's been running
  the corrected `rule_based`/5m/$2,000-cap config since 0.9.5), but the
  documentation was wrong and has been corrected in place rather than
  quietly edited away - see the "Current live status" section's
  correction note.
- **Rebuilt the status table again** after feedback that it still
  wasn't showing the same information for both asset classes: dropped
  the separate "Automation"/"Auto-trigger" rows (now identical for both,
  so stated once above the table instead of duplicated) and made every
  remaining row use parallel wording for crypto vs. stocks.

## Version Richards 0.9.7 - 2026-07-28

- **Fixed a real, live git-push race**, confirmed via GitHub Actions
  screenshots: while manually testing `paper-trade-stocks.yml` after the
  0.9.5/0.9.6 fixes, 2 of 4 runs failed at their "Commit trade log"
  step. Root cause: this workflow's own runs are serialized against each
  other by its `concurrency` group, but crypto's 5-minute schedule and
  the dashboard/retrain workflows all commit to the same
  `logs/equity_log.csv`, so two *different* workflows can still race to
  push at nearly the same moment - whichever loses hits a rebase
  conflict and previously just failed outright. Added a retry loop
  (pull --rebase + push, up to 5 attempts with `git rebase --abort`
  between them so a failed attempt doesn't block the next one) to all 4
  operational workflows' commit steps - a conflict here just means
  "someone else pushed first," not a real merge problem, so retrying
  after re-fetching resolves it almost every time.
- **Rebuilt the README's "Current live status" section** after feedback
  that it didn't explain crypto clearly and didn't show the same fields
  for both asset classes. Replaced the old single mixed table with a
  side-by-side crypto-vs-stocks comparison (automation state,
  auto-trigger, strategy, tickers, bar size, buy/sell signal, max $ per
  trade, daily loss breaker, demonstrated edge, closed trades) so
  neither asset class is missing information the other one has.
- **Added a plain explanation of what "79 tests passing" means**: fast,
  offline checks that specific code behaves correctly on made-up
  numbers (e.g. "does the stop-loss actually trigger at exactly -5%") -
  not proof either strategy makes money. That's a separate question,
  answered only by the backtests/grid searches/walk-forward validation
  described elsewhere in this README, never by the test suite.

## Version Richards 0.9.6 - 2026-07-28

- **Corrected the 2026-07-28 incident writeup: 3 tickers, not 2.**
  `logs/trade_log.csv` at the time showed QQQ, CAT, and DIS all bought
  at ~$11,087 each, not 2 tickers as first assumed - corrected in
  README.md and here.
- **Disabled `retrain-stock-model.yml`'s native GitHub schedule too**
  (`workflow_dispatch` only now), same reasoning as `paper-trade-
  stocks.yml` in 0.9.5 - `ml_filtered` isn't the live strategy right
  now, so there's no reason for this to run unattended either.
- **Archived the incident-tainted trade log.** `logs/trade_log.csv`
  (the 3 erroneous `ml_filtered` BUY rows) moved to
  `logs/trade_log_archive_pre_2026-07-28.csv`, `logs/trade_log.csv`
  restarted fresh with just its header - same precedent as the
  2026-07-25/07-27 rewrites. `logs/equity_log.csv` deliberately NOT
  archived (continuous truth, same reasoning as before). Regenerated
  `results/trade_dashboard.png` against both the archived and fresh
  logs before committing either, same verification as the earlier
  rewrites.
- **Fixed the intraday-stock annualization bug** flagged by an
  independent technical review of this repo: `main.py`/`optimize.py`/
  `walk_forward.py` previously used a 24/7 bars-per-year count
  (`PERIODS_PER_YEAR_24_7`) for ANY intraday interval regardless of
  asset class - correct for crypto (trades around the clock), wrong for
  stocks (regular market hours only, ~6.5 hours/day). Total return and
  max drawdown were never affected by this - only annualized return,
  annualized volatility, and Sharpe - and the 8-candidate stock
  comparison in 0.9.0/0.9.3 was based on total return and loss-rate, not
  Sharpe, so that conclusion stands unchanged. Added `src/data.py`'s
  `periods_per_year(interval, is_crypto)`, computed per-ticker (via
  `resolve_symbol().is_crypto`) everywhere a backtest is scored, so a
  single script run can never silently misjudge one asset class using
  the other's calendar. 3 new tests in `tests/test_data.py`.
- **Added a CI workflow** (`.github/workflows/ci.yml`): runs the full
  test suite on every push and PR. Previously this repo's only GitHub
  Actions workflows were operational (trading/retrain/dashboard) - a
  broken test could reach the default branch with nothing catching it.
  Deliberately scoped to just tests for now, not lint/type-check/
  dependency-audit - those need their own pass to see what they'd
  actually turn up on a codebase that's never had them, not to be
  bundled in blind.
- **Pinned all 5 GitHub Actions workflows' `actions/checkout` and
  `actions/setup-python` to full commit SHAs** (verified against the
  real upstream tags via `git ls-remote` - `v4` → `v4.4.0`
  `11d5960a326750d5838078e36cf38b85af677262`, `v5` → `v5.6.0`
  `a26af69be951a213d495a4c3e4e4022e16d87065`) instead of movable version
  tags, per GitHub's own secure-use guidance - a moving tag can be
  repointed by the action's maintainer (or, worse, an attacker who
  compromises their account) to different code without this repo
  changing a single line.
- **Added a model-file integrity check** to `src/model_store.py`:
  `save_model()` now records a SHA256 hash of the model file in its
  metadata sidecar; `load_model()` recomputes and compares it before
  calling `joblib.load()`, refusing to load (raising `ValueError`) on a
  mismatch. `joblib.load()` can execute arbitrary code for a tampered or
  corrupted file, and this one is written by an automation workflow then
  trusted unconditionally by live trading code later - this closes that
  gap for any file saved from now on. Models saved before this check
  existed (no recorded hash) still load, with a warning, since there's
  nothing to verify them against. 5 new tests in
  `tests/test_model_store.py` (previously zero coverage for this file).
- These fixes came from a second-opinion technical review of this
  repository (an independent LLM-generated assessment) - agreed with:
  the annualization bug, missing CI, unpinned Actions, and the
  `joblib.load()` concern, all verified against the actual code before
  fixing, not taken on faith. Deliberately NOT done, as disproportionate
  for a solo paper-trading research project: migrating logs off Git to
  a real database, signed/attested model artifacts, and a full
  microservices-style research/execution/reporting split. Also
  deliberately no `LICENSE` file added - the account owner prefers the
  default "all rights reserved" protection that gives over an open
  license.

## Version Richards 0.9.5 - 2026-07-28

- **Fixed a second live stock incident.** Despite the README/CHANGELOG
  declaring stocks "paused" as of 0.8.0, `.github/workflows/
  paper-trade-stocks.yml` still had its own native GitHub `schedule:`
  trigger. Confirmed via the GitHub Actions API: the run that placed
  these trades has `event: "schedule"`, fired at 2026-07-27T23:41:42Z -
  nearly 4 hours after its own `55 19 * * 1-5` (~19:55 UTC) cron target,
  a known failure mode for this trigger in this project, previously seen
  as "silently doesn't fire" and this time as "fires very late instead."
  The Actions history also shows the cron-job.org job for this workflow
  had independently remained active the whole time (`workflow_dispatch`
  runs at ~19:55 UTC on 2026-07-25 and 2026-07-26, no trades those days)
  - so "paused" wasn't enforced on either path. Both were still running
  a stale `--strategy ml_filtered --dip-threshold -0.03` command from
  before this session's walk-forward work - not the validated best-of-8
  candidate. That combination bought **3 tickers - QQQ, CAT, and DIS,
  ~$11,087 each** (confirmed from `logs/trade_log.csv`) on the paper
  account without the account owner intending to be trading stocks at
  all. The owner is canceling/closing all 3 positions manually.
- **Structural fix, not just a documentation update:** removed the
  `schedule:` trigger from `paper-trade-stocks.yml` entirely - only
  `workflow_dispatch: {}` remains, so GitHub itself cannot fire this
  workflow on its own anymore; only a manual click or an external
  scheduler call can. "Paused" from here on means the workflow
  structurally cannot run unattended, not merely that a doc says it
  shouldn't.
- Corrected the workflow's committed strategy to the actual best-of-8
  walk-forward candidate identified in 0.9.3/0.9.4: `rule_based`,
  `--interval 5m`, `--dip-threshold -0.015 --exit-threshold 0.02` -
  previously it ran `ml_filtered` with a threshold that was never part
  of any candidate this session validated. Also added
  `--max-notional 2000 --daily-loss-limit 0.05`, mirroring the caps
  `paper-trade-crypto.yml` already had - stocks were missing both
  entirely, the same gap the first (QQQ) incident found in 0.8.0.
- Updated `docs/AUTOMATION.md` and the README's file tree/status table:
  the live stock cadence is now "every ~5 minutes during market hours"
  (matching the 5-minute-bar candidate actually wired in), not "once
  daily near market close" - running a 5-minute-bar strategy once a day
  would not reproduce its validated behavior. `ml_filtered` and
  `retrain-stock-model.yml` remain available for anyone who wants to
  keep researching that path, but are no longer what the live workflow
  runs.

## Version Richards 0.9.4 - 2026-07-27

- Added a per-ticker small-multiples bar chart for the best-of-8 stock
  candidate (`rule_based`, 5-minute bars, `dip=-1.5% exit=2.0%`):
  `results/walk_forward/walk_forward_stocks_5m_best_candidate.png`, one panel per
  ticker (SPY, AAPL, QQQ, JPM, XOM, JNJ, KO, CAT, DIS) showing its return
  in each of the 7 walk-forward windows, matching the style already used
  for the daily candidate chart. Previously the winning candidate only
  had aggregate numbers shown (summary bar chart, scatter); this makes
  its actual per-ticker behavior visible, including which tickers never
  traded (SPY, KO - mostly gray) and which one is the clear weak point
  (DIS - 4 of 7 windows negative). Its raw per-window data is newly
  committed as `results/walk_forward/walk_forward_stocks_5m_best.csv`, cross-checked
  against the already-committed summary row (avg return and losing-window
  count both matched before anything was written).
- Embedded this new chart directly in the README (immediately after the
  summary comparison chart, in the stock-validation bullet) and in
  `docs/RESEARCH.md`'s final-tally section, so the clearest per-ticker
  evidence for the best stock candidate is visible on the README itself,
  not only in the supporting research doc.

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
- `results/walk_forward/walk_forward_stocks_summary.png`,
  `results/param_sweep/param_sweep_overview_stocks_5m_all.png`, and
  `results/param_sweep/param_sweep_overview_stocks_daily_all.png` regenerated to
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
  [`results/walk_forward/walk_forward_stocks_summary.png`](results/walk_forward/walk_forward_stocks_summary.png)
  (all 8 candidates' return/consistency side by side),
  [`results/param_sweep/param_sweep_overview_stocks_daily_all.png`](results/param_sweep/param_sweep_overview_stocks_daily_all.png)
  and
  [`results/param_sweep/param_sweep_overview_stocks_5m_all.png`](results/param_sweep/param_sweep_overview_stocks_5m_all.png)
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

- Fixed: `results/walk_forward/walk_forward_winner.png` (the crypto walk-forward chart)
  labeled each bar by its window's **start** date, so the final window
  (2026-05-28 -> 2026-07-27) only ever showed "May '26" - June and July
  2026 never appeared as labels even though the chart's own title
  correctly states the data runs through July 2026, and the underlying
  `results/walk_forward/walk_forward.csv` data was always correct. Regenerated with
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
  [`results/param_sweep/param_sweep_stocks.csv`](results/param_sweep/param_sweep_stocks.csv) (top
  15 of an 18-combo `optimize.py --strategy rule_based` grid search,
  2022-01-01 to 2026-07-27 held out) and
  [`results/walk_forward/walk_forward_stocks.csv`](results/walk_forward/walk_forward_stocks.csv)
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
  `results/param_sweep/param_sweep_overview.png` and `results/walk_forward/walk_forward_winner.png`
  are committed too:
  [`results/param_sweep/param_sweep_overview_stocks.png`](results/param_sweep/param_sweep_overview_stocks.png)
  and
  [`results/walk_forward/walk_forward_stocks_candidate.png`](results/walk_forward/walk_forward_stocks_candidate.png)
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

- Added: `results/param_sweep/param_sweep_overview.png` and
  `results/walk_forward/walk_forward_winner.png` - rendered charts of the 0.7.0
  evidence CSVs, generated straight from `results/param_sweep/param_sweep.csv` and
  `results/walk_forward/walk_forward.csv` (not hand-edited), embedded in README's
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
- Added: `results/param_sweep/param_sweep.csv` - the full 90-combination grid search
  (`optimize.py`, real Alpaca 5-minute data, 2025-08-01 to 2026-07-27)
  that surfaced this combo as the best average-return result, with its
  closest neighbors (same dip/profit, different stop) landing within a
  couple points of each other - the "not an isolated overfit spike"
  check `docs/RESEARCH.md` describes.
  `worst_ticker_return` on the top two rows is **positive** - every one
  of the 9 coins was profitable, not just the average.
- Added: `results/walk_forward/walk_forward.csv` - the walk-forward validation of
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
  `results/walk_forward/walk_forward.csv` (`--out` to change the path), matching
  `optimize.py`'s existing `results/param_sweep/param_sweep.csv` output - every
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
