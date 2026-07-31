/*
 * InvestingBot dashboard frontend.
 *
 * Loads the JSON files site_data.py generates (data/dashboard.json,
 * positions.json, trades.json) and renders them. Every fetch is wrapped
 * so a missing, empty, or malformed file degrades to a clearly-labeled
 * empty state instead of a broken page or a console error the visitor
 * never sees. Nothing here fabricates a number - if a file didn't load,
 * the corresponding widget says so.
 */

(function () {
  "use strict";

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let dashboard = null;
  let positions = null;
  let positionIndicators = null;
  let tickerTracker = null;
  let trades = null;
  let equity = null;
  let backtestComparison = null;
  let currentPeriod = "today";  // controls the metric row + performance summary (period selector)
  // The full, unfiltered trade rows currently loaded, each stamped with
  // its own stable index (__idx) into trades.trades - the trade detail
  // modal looks a row up by this index, so it always finds the exact
  // same record clicked regardless of whatever the search filter above
  // the table currently has typed into it.
  let currentLedgerRows = [];

  // ---------------------------------------------------------------------
  // Safe fetch: never throws, never lets one bad file break the others.
  // ---------------------------------------------------------------------
  async function loadJson(name, fallback) {
    try {
      const res = await fetch(DATA_BASE + name, { cache: "no-store" });
      if (!res.ok) {
        console.warn(`[investingbot] ${name} responded with HTTP ${res.status} - using fallback.`);
        return fallback;
      }
      const text = await res.text();
      if (!text || !text.trim()) {
        console.warn(`[investingbot] ${name} was empty - using fallback.`);
        return fallback;
      }
      try {
        return JSON.parse(text);
      } catch (parseErr) {
        console.warn(`[investingbot] ${name} was malformed JSON - using fallback.`, parseErr);
        return fallback;
      }
    } catch (networkErr) {
      console.warn(`[investingbot] ${name} could not be fetched (offline? missing file?) - using fallback.`, networkErr);
      return fallback;
    }
  }

  // ---------------------------------------------------------------------
  // Formatting helpers
  // ---------------------------------------------------------------------
  function fmtUsd(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtUsdSigned(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + fmtUsd(v);
  }
  function fmtPct(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
  }
  function fmtQty(v) {
    if (v === null || v === undefined) return "—";
    return Number(v).toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  function fmtEt(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    const formatted = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    }).format(d);
    return formatted + " ET";
  }
  function signClass(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "";
    return v > 0 ? "positive" : v < 0 ? "negative" : "";
  }

  // ---------------------------------------------------------------------
  // Headline metric row
  // ---------------------------------------------------------------------
  // Each metric carries its own raw number (for the count-up animation
  // below to interpolate through) alongside the formatter that turns
  // any intermediate value into the same display string a final one
  // would get - so a mid-animation frame for, say, win_rate still reads
  // "37%" in the right format, not a bare unformatted float.
  const METRIC_DEFS = {
    equity: (p) => ({ raw: p.ending_value_usd, fmt: fmtUsd, cls: "" }),
    period_pnl: (p) => ({ raw: p.dollar_pnl_usd, fmt: fmtUsdSigned, cls: signClass(p.dollar_pnl_usd) }),
    pct_return: (p) => ({ raw: p.pct_return, fmt: fmtPct, cls: signClass(p.pct_return) }),
    win_rate: (p) => ({ raw: p.win_rate, fmt: (v) => (v * 100).toFixed(0) + "%", cls: "" }),
    num_trades: (p) => ({ raw: p.num_trades ?? 0, fmt: (v) => String(Math.round(v)), cls: "" }),
    unrealized: (p) => ({ raw: p.unrealized_pnl_usd, fmt: fmtUsdSigned, cls: signClass(p.unrealized_pnl_usd) }),
  };

  // Count-up/down animation for the headline metric cards: switching
  // Today/Week/Month/All Time (or the initial load) animates each
  // number from whatever it last showed to its new real value, instead
  // of an instant snap. Purely cosmetic - the final displayed value is
  // always the same exact real number regardless of animation.
  const METRIC_ANIM_MS = 650;
  const lastMetricValue = new WeakMap();

  function animateMetric(el, raw, fmt, finalClass) {
    el.classList.remove("positive", "negative");
    if (finalClass) el.classList.add(finalClass);

    if (raw === null || raw === undefined || Number.isNaN(raw)) {
      lastMetricValue.delete(el);
      el.textContent = "—";
      return;
    }

    const hasPrior = lastMetricValue.has(el);
    const from = hasPrior ? lastMetricValue.get(el) : raw;
    lastMetricValue.set(el, raw);

    // No prior value (first paint) or reduced-motion: show the real
    // number immediately rather than counting up from zero/nothing,
    // which would itself read as a fabricated intermediate value.
    if (!hasPrior || REDUCED_MOTION || from === raw) {
      el.textContent = fmt(raw);
      return;
    }

    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / METRIC_ANIM_MS);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = fmt(from + (raw - from) * eased);
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------------
  // Account-value sparkline (headline "equity" card only) - drawn from
  // the same equity.json series charts.html plots, filtered to whichever
  // period is currently selected. Real recorded points only; if fewer
  // than 2 fall inside the period the card shows no line rather than a
  // misleadingly flat/fabricated one.
  // ---------------------------------------------------------------------
  const SPARK_WIN = "#34d372";
  const SPARK_LOSS = "#f0554a";

  function periodEquitySeries(p) {
    if (!equity || !equity.available || !Array.isArray(equity.points) || !equity.points.length) return null;
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const endMs = p.end_utc ? new Date(p.end_utc).getTime() : Infinity;
    const vals = equity.points
      .filter((pt) => {
        const t = new Date(pt.timestamp_utc).getTime();
        return !Number.isNaN(t) && t >= startMs && t <= endMs;
      })
      .map((pt) => pt.portfolio_value_usd)
      .filter((v) => typeof v === "number" && !Number.isNaN(v));
    return vals.length >= 2 ? vals : null;
  }

  function sparklineSvg(values) {
    const w = 100, h = 28, pad = 2;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const stepX = (w - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => {
      const x = pad + i * stepX;
      const y = pad + (1 - (v - min) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const color = values[values.length - 1] >= values[0] ? SPARK_WIN : SPARK_LOSS;
    const area = `${pad},${h - pad} ${pts.join(" ")} ${w - pad},${h - pad}`;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">` +
      `<polyline points="${area}" fill="${color}" fill-opacity="0.1" stroke="none"></polyline>` +
      `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" ` +
      `stroke-linejoin="round" stroke-linecap="round"></polyline></svg>`;
  }

  function renderSpark(el, p) {
    const series = periodEquitySeries(p);
    el.innerHTML = series ? sparklineSvg(series) : "";
  }

  // Position/tracker card sparklines - a small "spark" array site_data.py
  // already publishes per ticker (see build_positions_payload/
  // build_ticker_tracker's own _sparkline_closes calls): the rolling
  // 20-period/5-minute average over time, the exact same signal already
  // shown as this card's own "vs 20-bar avg" text stat - not raw price,
  // and not since-purchase. Reuses the exact same sparklineSvg() the
  // headline equity card draws with, just fed a different series - one
  // sparkline renderer for the whole site, not two. Omitted entirely
  // (not drawn as a flat/fabricated line) when a ticker's own spark
  // fetch failed. The hover tooltip/aria-label exists because this had
  // no on-card label at all before and was genuinely ambiguous.
  const SPARK_TOOLTIP = "Rolling 20-bar/5-min average, not raw price or since-purchase";
  function cardSparkHtml(spark, cls) {
    if (!Array.isArray(spark) || spark.length < 2) return "";
    return `<div class="${cls}" data-tooltip="${SPARK_TOOLTIP}" aria-label="${SPARK_TOOLTIP}">${sparklineSvg(spark)}</div>`;
  }

  // Hovering the headline Win Rate card reveals the real win/loss count
  // it's computed from - the same num_wins/num_losses the stats grid
  // below already shows as its own separate tiles, just surfaced here
  // too since a visitor glancing only at the headline row otherwise has
  // no way to see "37% of *what*" without scrolling down.
  function winRateTooltip(card, p) {
    if (p.win_rate === null || p.num_wins === undefined || p.num_losses === undefined) {
      card.removeAttribute("data-tooltip");
      return;
    }
    const wins = `${p.num_wins} win${p.num_wins === 1 ? "" : "s"}`;
    const losses = `${p.num_losses} loss${p.num_losses === 1 ? "" : "es"}`;
    card.setAttribute("data-tooltip", `${wins} · ${losses}`);
  }

  function renderMetricRow(period) {
    const p = dashboard.periods[period];
    document.querySelectorAll(".metric-card[data-metric]").forEach((card) => {
      const key = card.dataset.metric;
      const def = METRIC_DEFS[key];
      if (!def) return;
      const { raw, fmt, cls } = def(p);
      animateMetric(card.querySelector("[data-value]"), raw, fmt, cls);
      const sparkEl = card.querySelector("[data-spark]");
      if (sparkEl) renderSpark(sparkEl, p);
      if (key === "win_rate") winRateTooltip(card, p);
    });
  }

  // ---------------------------------------------------------------------
  // Performance summary grid
  // ---------------------------------------------------------------------
  function metricCard(label, value, opts) {
    opts = opts || {};
    const cls = opts.cls || "";
    const sub = opts.sub ? `<div class="metric-sub">${opts.sub}</div>` : "";
    return `<div class="metric-card"><div class="metric-label">${label}</div><div class="metric-value ${cls}">${value}</div>${sub}</div>`;
  }

  function renderStatsGrid(period) {
    const p = dashboard.periods[period];
    document.getElementById("period-label").textContent = p.label;
    const startNote = p.starting_value_is_first_available
      ? "first value logged in this period (no earlier data to carry forward)"
      : (p.start_utc ? `as of ${fmtEt(p.start_utc)}` : "start of all logged history");

    const tiles = [
      metricCard("Starting Value", fmtUsd(p.starting_value_usd), { sub: startNote }),
      metricCard("Ending Value", fmtUsd(p.ending_value_usd)),
      metricCard("Dollar P&amp;L", fmtUsdSigned(p.dollar_pnl_usd), { cls: signClass(p.dollar_pnl_usd) }),
      metricCard("% Return", fmtPct(p.pct_return), { cls: signClass(p.pct_return) }),
      metricCard("Realized P&amp;L", fmtUsdSigned(p.realized_pnl_usd), { cls: signClass(p.realized_pnl_usd) }),
      metricCard("Unrealized P&amp;L", fmtUsdSigned(p.unrealized_pnl_usd), { cls: signClass(p.unrealized_pnl_usd) }),
      metricCard("Trades (closed)", p.num_trades, { sub: `${p.num_buys ?? 0} buys, ${p.num_unconfirmed ?? 0} unconfirmed, ${p.num_not_placed ?? 0} not placed` }),
      metricCard("Winning Trades", p.num_wins),
      metricCard("Losing Trades", p.num_losses),
      metricCard("Win Rate", p.win_rate === null ? "—" : (p.win_rate * 100).toFixed(1) + "%"),
      metricCard("Best Trade", p.best_trade ? `${p.best_trade.ticker} ${fmtUsdSigned(p.best_trade.realized_pnl_usd)}` : "—", { cls: p.best_trade ? "positive" : "" }),
      metricCard("Worst Trade", p.worst_trade ? `${p.worst_trade.ticker} ${fmtUsdSigned(p.worst_trade.realized_pnl_usd)}` : "—", { cls: p.worst_trade ? "negative" : "" }),
      metricCard("Max Drawdown", p.max_drawdown === null ? "not enough data" : fmtPct(p.max_drawdown), { cls: p.max_drawdown ? "negative" : "" }),
    ];
    document.getElementById("stats-grid").innerHTML = tiles.join("");

    document.getElementById("methodology-note").innerHTML =
      `<strong>How this is calculated:</strong> ${dashboard.methodology.baseline}. ${dashboard.methodology.num_trades}`;
  }

  // ---------------------------------------------------------------------
  // Account strip (cash / buying power / equity) - independent of period
  // ---------------------------------------------------------------------
  // Live-ticking "(2m ago)" next to the absolute timestamp, so it's
  // obvious at a glance the page is actually current without needing to
  // reload - re-rendered on an interval below, purely from the one
  // generated_at_utc timestamp already loaded, no refetch involved.
  let generatedAtMs = null;

  function fmtRelativeTime(fromMs) {
    if (fromMs === null || Number.isNaN(fromMs)) return "";
    const diffSec = Math.max(0, Math.round((Date.now() - fromMs) / 1000));
    if (diffSec < 45) return " (just now)";
    const diffMin = Math.round(diffSec / 60);
    if (diffMin < 60) return ` (${diffMin}m ago)`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return ` (${diffHr}h ago)`;
    return ` (${Math.round(diffHr / 24)}d ago)`;
  }

  function tickLastUpdatedRelative() {
    const el = document.getElementById("last-updated-relative");
    if (el) el.textContent = fmtRelativeTime(generatedAtMs);
  }

  function renderAccountStrip() {
    const a = dashboard.account;
    document.getElementById("stat-cash").textContent = fmtUsd(a.cash_usd);
    document.getElementById("stat-buying-power").textContent = fmtUsd(a.buying_power_usd);
    document.getElementById("stat-equity").textContent = fmtUsd(a.equity_usd);
    document.getElementById("last-updated").textContent =
      `Last updated: ${fmtEt(dashboard.generated_at_utc)} (${dashboard.generated_at_utc} UTC)` +
      (a.available ? "" : " — live account figures unavailable this run, showing logged data only");
    generatedAtMs = new Date(dashboard.generated_at_utc).getTime();
    tickLastUpdatedRelative();
  }

  // ---------------------------------------------------------------------
  // Open positions
  // ---------------------------------------------------------------------
  // rule_based/ml_filtered positions sell on a mean-reversion recovery
  // vs. their own 20-period SMA (see site_data.py's
  // build_position_sma_indicators) rather than vs. entry price - that's
  // a different number than the unrealized P&L row above, and the one
  // this project's live logs never otherwise surface for a held stock
  // position. day_trading (crypto) positions sell on gain-vs-entry
  // instead, which the unrealized P&L row already shows, so this row is
  // deliberately omitted for them rather than showing a second,
  // unrelated number.
  function positionSmaRow(p) {
    if (p.strategy !== "rule_based" && p.strategy !== "ml_filtered") return "";
    if (!positionIndicators || !positionIndicators.available) return "";
    const ind = positionIndicators.symbols ? positionIndicators.symbols[p.symbol] : null;
    if (!ind) return "";
    const threshold = ind.exit_threshold;
    if (!ind.available || ind.pct_vs_sma20 === null || ind.pct_vs_sma20 === undefined) {
      return `<div class="position-card-row position-card-sma"><span>vs 20-bar avg</span><span>—</span></div>`;
    }
    const label = threshold !== null && threshold !== undefined
      ? `${fmtPct(ind.pct_vs_sma20)} (sells at ${fmtPct(threshold)})`
      : fmtPct(ind.pct_vs_sma20);
    return `<div class="position-card-row position-card-sma"><span>vs 20-bar avg</span><span class="${signClass(ind.pct_vs_sma20)}">${label}</span></div>`;
  }

  function positionCard(p) {
    const pnl = p.unrealized_pl;
    const trend = pnl > 0 ? "trend-up" : pnl < 0 ? "trend-down" : "";
    const strategyLabel = p.strategy || "unknown";
    // data-symbol is the bare ticker (p.ticker, e.g. "BTC" - not Alpaca's
    // own "BTCUSD") so assets/position-chart.js (a separate, shared
    // script - see that file) can open this exact ticker's price chart
    // on click by keying straight into ticker_charts.json, the same file
    // every Ticker Tracker card already reads - one click-to-chart
    // implementation for every card sitewide, not two.
    return `
      <div class="position-card ${trend}" data-symbol="${p.ticker}" data-is-crypto="${p.is_crypto}" tabindex="0" role="button" aria-haspopup="dialog">
        <div class="position-card-head">
          <span class="position-card-ticker">${p.symbol}</span>
          <span class="position-card-strategy strategy-${strategyLabel}">${strategyLabel}</span>
        </div>
        ${cardSparkHtml(p.spark, "position-card-spark")}
        <div class="position-card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="position-card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="position-card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="position-card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        ${positionSmaRow(p)}
        <div class="position-card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPct(p.unrealized_plpc)})</div>
        <div class="position-card-hint">View price history →</div>
      </div>`;
  }

  function renderPositions() {
    const stockEl = document.getElementById("hand-stocks");
    const cryptoEl = document.getElementById("hand-crypto");
    if (!positions || !positions.available) {
      const msg = `<p class="empty-state">${positions && positions.reason ? positions.reason : "Live positions weren't fetched for this run."}</p>`;
      stockEl.innerHTML = msg;
      cryptoEl.innerHTML = msg;
      return;
    }
    const stocks = positions.positions.filter((p) => !p.is_crypto);
    const cryptos = positions.positions.filter((p) => p.is_crypto);
    stockEl.innerHTML = stocks.length ? stocks.map(positionCard).join("") : '<p class="empty-state">No open stock positions right now.</p>';
    cryptoEl.innerHTML = cryptos.length ? cryptos.map(positionCard).join("") : '<p class="empty-state">No open crypto positions right now.</p>';
  }

  // ---------------------------------------------------------------------
  // Ticker Tracker - every ticker either live workflow watches, not just
  // the ones currently held (see site_data.py's build_ticker_tracker).
  // A held ticker's card is outlined green (in profit) or red (at a
  // loss) - the same signal a position card's own trend-up/trend-down
  // border already gives; a watched-but-not-held ticker gets a neutral
  // grey outline instead of no outline at all, so "not held" reads as a
  // deliberate state rather than a rendering gap.
  // ---------------------------------------------------------------------
  // Each of the two SMA readings (100-day, 20-bar/5-minute) has its own
  // independent available/reason pair (see site_data.py's
  // build_ticker_tracker) - one failing to fetch never hides the other,
  // so each gets rendered separately rather than one all-or-nothing gate.
  function trackerCard(row) {
    const stateClass = "tracker-state-" + row.position_state.replace("_", "-");
    const heldBadge = row.held ? '<span class="tracker-card-badge">Held</span>' : "";
    const rows = [];
    if (row.available) {
      rows.push(`<div class="tracker-card-row"><span>Last Close</span><span>${fmtUsd(row.last_close)}</span></div>`);
      rows.push(`<div class="tracker-card-row"><span>100-Day Avg</span><span>${fmtUsd(row.sma100)}</span></div>`);
    }
    if (row.sma20_available) {
      rows.push(`<div class="tracker-card-row"><span>20-Bar Avg</span><span>${fmtUsd(row.sma20)}</span></div>`);
    }
    let body = rows.join("");
    if (row.available) {
      const deltaClass = row.pct_vs_sma100 >= 0 ? "positive" : "negative";
      body += `<div class="tracker-card-delta ${deltaClass}">${fmtPct(row.pct_vs_sma100)} vs 100-day avg</div>`;
    }
    if (row.sma20_available) {
      const deltaClass20 = row.pct_vs_sma20 >= 0 ? "positive" : "negative";
      body += `<div class="tracker-card-delta ${deltaClass20}">${fmtPct(row.pct_vs_sma20)} vs 20-bar avg</div>`;
    }
    if (!row.available && !row.sma20_available) {
      body = `<p class="tracker-card-unavailable">${row.reason || row.sma20_reason || "Price data unavailable."}</p>`;
    }
    // data-symbol/data-is-crypto let assets/position-chart.js (a
    // separate, shared script) open this ticker's range-selectable
    // price chart on click - same click-delegation contract every
    // position card sitewide already uses (see positionCard() above),
    // both reading the same ticker_charts.json.
    return `
      <div class="tracker-card ${stateClass}" data-symbol="${row.ticker}" data-is-crypto="${row.is_crypto}" tabindex="0" role="button" aria-haspopup="dialog">
        <div class="tracker-card-head">
          <span class="tracker-card-ticker">${row.ticker}</span>
          ${heldBadge}
        </div>
        ${cardSparkHtml(row.spark, "tracker-card-spark")}
        ${body}
        <div class="tracker-card-hint">View chart →</div>
      </div>`;
  }

  function renderTickerTracker() {
    const stockEl = document.getElementById("tracker-stocks");
    const cryptoEl = document.getElementById("tracker-crypto");
    if (!tickerTracker || !tickerTracker.available) {
      const msg = `<p class="empty-state">${(tickerTracker && tickerTracker.reason) || "Ticker tracker data wasn't fetched for this run."}</p>`;
      stockEl.innerHTML = msg;
      cryptoEl.innerHTML = msg;
      return;
    }
    const stocks = tickerTracker.categories.stocks || [];
    const cryptos = tickerTracker.categories.crypto || [];
    stockEl.innerHTML = stocks.length ? stocks.map(trackerCard).join("") : '<p class="empty-state">No watched stock tickers configured.</p>';
    cryptoEl.innerHTML = cryptos.length ? cryptos.map(trackerCard).join("") : '<p class="empty-state">No watched crypto tickers configured.</p>';
  }

  // ---------------------------------------------------------------------
  // Trade history - deliberately NOT filtered by the period selector
  // above (or by the charts page's own period dropdown, which lives
  // entirely on charts.html): this section always shows the most recent
  // real history regardless of whatever period the rest of the page is
  // currently scoped to.
  // ---------------------------------------------------------------------
  const STATUS_LABEL = {
    confirmed_fill: "Confirmed Fill",
    submitted_unconfirmed: "Submitted, Unconfirmed",
    not_placed: "Not Placed",
  };
  const STATUS_BADGE_CLASS = {
    confirmed_fill: "badge-confirmed",
    submitted_unconfirmed: "badge-unconfirmed",
    not_placed: "badge-notplaced",
  };

  // One consistent per-strategy accent color everywhere a strategy name
  // shows up as its own pill (Trade History's Strategy column, the
  // trade detail modal) - see the .strategy-pill/.strategy-* CSS rules.
  function strategyPillHtml(strategy) {
    const key = strategy || "unknown";
    return `<span class="strategy-pill strategy-${key}">${key}</span>`;
  }

  function ledgerRowHtml(t) {
    const pnlCls = t.realized_pnl_usd === null ? "" : (t.realized_pnl_usd >= 0 ? "pnl-positive" : "pnl-negative");
    const qtyOrNotional = t.notional_usd !== null ? fmtUsd(t.notional_usd) : fmtQty(t.position_qty_before);
    // data-trade-idx lets the click/keyboard handlers below (wired once,
    // in boot()) open the trade detail modal for this exact row without
    // needing to re-derive which trade it is from displayed text.
    return `<tr data-trade-idx="${t.__idx}" tabindex="0" role="button" aria-haspopup="dialog">
        <td>${fmtEt(t.timestamp_utc)}</td>
        <td>${t.asset_class}</td>
        <td>${t.ticker}</td>
        <td>${strategyPillHtml(t.strategy)}</td>
        <td>${t.action}</td>
        <td>${fmtUsd(t.price_usd)}${t.price_is_confirmed_fill ? "" : " (est.)"}</td>
        <td>${qtyOrNotional}</td>
        <td class="${pnlCls}">${t.realized_pnl_usd === null ? "—" : fmtUsdSigned(t.realized_pnl_usd)}</td>
        <td><span class="badge ${STATUS_BADGE_CLASS[t.order_status] || ""}">${STATUS_LABEL[t.order_status] || t.order_status}</span></td>
        <td>${t.notes || ""}</td>
      </tr>`;
  }

  // A trade matches the filter if the typed text appears in any of its
  // own real fields - never a fuzzy/guessed match, just a plain
  // case-insensitive substring search across exactly what's displayed
  // (or, for notes, the same text the detail modal also shows in full).
  function tradeMatchesFilter(t, needle) {
    if (!needle) return true;
    const haystack = [t.ticker, t.strategy, t.action, t.asset_class, t.order_status, t.notes]
      .filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(needle);
  }

  function applyLedgerFilter() {
    const filterInput = document.getElementById("ledger-filter");
    const filterEmpty = document.getElementById("ledger-filter-empty");
    const countEl = document.getElementById("ledger-filter-count");
    const scrollEl = document.querySelector("#ledger-table")?.closest(".table-scroll");
    const needle = ((filterInput && filterInput.value) || "").trim().toLowerCase();
    const rows = currentLedgerRows.filter((t) => tradeMatchesFilter(t, needle));
    document.getElementById("ledger-body").innerHTML = rows.map(ledgerRowHtml).join("");
    const noMatches = needle && rows.length === 0;
    if (filterEmpty) filterEmpty.hidden = !noMatches;
    if (scrollEl) scrollEl.hidden = noMatches;
    if (countEl) countEl.textContent = needle ? `${rows.length} of ${currentLedgerRows.length} shown` : "";
  }

  function renderLedger() {
    const body = document.getElementById("ledger-body");
    const empty = document.getElementById("ledger-empty");
    const filterEl = document.querySelector(".table-filter");
    if (!trades || !trades.available || !trades.trades.length) {
      body.innerHTML = "";
      currentLedgerRows = [];
      empty.hidden = false;
      empty.textContent = "No trades logged yet.";
      if (filterEl) filterEl.hidden = true;
      return;
    }
    empty.hidden = true;
    if (filterEl) filterEl.hidden = false;
    // Already newest-first, capped server-side (site_data.py's
    // MAX_TRADES_PUBLISHED) - stamped with a stable index here so the
    // detail modal and the filter above can both reference the exact
    // same underlying record.
    currentLedgerRows = trades.trades.map((t, i) => Object.assign({}, t, { __idx: i }));
    applyLedgerFilter();
  }

  // ---------------------------------------------------------------------
  // Trade detail modal - opened by clicking (or Enter/Space-selecting)
  // any row in Trade History. Shows every field this project's trade
  // log actually records for that row - richer than the table's own
  // abbreviated columns (full mode/notes text, cost basis, whether the
  // fill was confirmed) - plus a plain description of that strategy's
  // real, already-documented rule.
  //
  // Deliberately does NOT show "indicator values at decision time" (the
  // exact SMA/dip % the bot saw when it traded): live_trade.py's own
  // trade log never records those - TRADE_LOG_FIELDS's own comment says
  // outright that "notes" is only ever a fill-confirmation status
  // string, never decision reasoning. Showing invented numbers here
  // would be exactly the kind of fabrication every other panel on this
  // site goes out of its way never to do, so the honest version of this
  // feature is "every real field, clearly labeled" plus one sentence
  // explaining that gap - not a richer chart this project's own logs
  // don't actually support yet.
  // ---------------------------------------------------------------------
  const STRATEGY_RULE_TEXT = {
    rule_based: "Buys a stock after a dip at least its configured threshold below a short moving average, then sells once price recovers to a set percentage above its own 20-period average.",
    ml_filtered: "Same dip-and-recovery rule as rule_based, but a trained model also has to agree the dip looks like a real buying opportunity before the trade is placed.",
    day_trading: "Crypto-only: buys after a dip of its configured threshold, then sells on either a fixed profit target or a stop-loss, whichever comes first - never held overnight.",
  };

  let lastTradeFocused = null;

  function ensureTradeModal() {
    if (document.getElementById("trade-modal-backdrop")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="trade-modal-backdrop" id="trade-modal-backdrop" hidden>
        <div class="trade-modal" id="trade-modal" role="dialog" aria-modal="true" aria-labelledby="trade-modal-title">
          <button type="button" class="trade-modal-close" id="trade-modal-close" aria-label="Close trade detail">&times;</button>
          <div class="trade-modal-head">
            <h2 class="trade-modal-title" id="trade-modal-title">—</h2>
            <p class="trade-modal-sub" id="trade-modal-sub"></p>
          </div>
          <div class="trade-modal-rows" id="trade-modal-rows"></div>
          <p class="trade-modal-rule" id="trade-modal-rule" hidden></p>
          <p class="trade-modal-honesty">Decision-time indicator values (the exact SMA/dip % the bot saw) aren't recorded in the trade log - only the fields above are actually logged.</p>
        </div>
      </div>`;
    document.body.appendChild(wrap.firstElementChild);
    document.getElementById("trade-modal-close").addEventListener("click", closeTradeModal);
    document.getElementById("trade-modal-backdrop").addEventListener("click", (e) => {
      if (e.target.id === "trade-modal-backdrop") closeTradeModal();
    });
    document.addEventListener("keydown", (e) => {
      const backdrop = document.getElementById("trade-modal-backdrop");
      if (!backdrop || backdrop.hidden) return;
      if (e.key === "Escape") closeTradeModal();
    });
  }

  function tradeDetailRow(label, value, cls) {
    return `<div class="trade-modal-row"><span>${label}</span><span class="${cls || ""}">${value}</span></div>`;
  }

  function openTradeModal(idx) {
    const t = currentLedgerRows.find((r) => r.__idx === idx);
    if (!t) return;
    lastTradeFocused = document.activeElement;
    ensureTradeModal();
    const backdrop = document.getElementById("trade-modal-backdrop");
    const pnlCls = t.realized_pnl_usd === null ? "" : signClass(t.realized_pnl_usd);

    document.getElementById("trade-modal-title").textContent = `${t.ticker} — ${t.action}`;
    document.getElementById("trade-modal-sub").textContent = `${fmtEt(t.timestamp_utc)} · ${t.mode || "—"} · ${t.asset_class}`;

    const rows = [
      tradeDetailRow("Strategy", strategyPillHtml(t.strategy)),
      tradeDetailRow("Status", `<span class="badge ${STATUS_BADGE_CLASS[t.order_status] || ""}">${STATUS_LABEL[t.order_status] || t.order_status}</span>`),
      tradeDetailRow("Price", `${fmtUsd(t.price_usd)}${t.price_is_confirmed_fill ? " (confirmed fill)" : " (decision-time estimate - fill not confirmed)"}`),
      t.notional_usd !== null ? tradeDetailRow("Notional", fmtUsd(t.notional_usd)) : tradeDetailRow("Qty held before this trade", fmtQty(t.position_qty_before)),
      t.avg_entry_price_usd !== null ? tradeDetailRow("Avg Entry (cost basis)", fmtUsd(t.avg_entry_price_usd)) : "",
      t.realized_pnl_usd !== null ? tradeDetailRow("Realized P&amp;L", fmtUsdSigned(t.realized_pnl_usd), pnlCls) : "",
      t.notes ? tradeDetailRow("System Note", t.notes) : "",
    ].filter(Boolean).join("");
    document.getElementById("trade-modal-rows").innerHTML = rows;

    const ruleEl = document.getElementById("trade-modal-rule");
    const ruleText = STRATEGY_RULE_TEXT[t.strategy];
    ruleEl.hidden = !ruleText;
    if (ruleText) ruleEl.textContent = `${t.strategy}'s rule: ${ruleText}`;

    backdrop.hidden = false;
    document.body.classList.add("trade-modal-open");
    document.getElementById("trade-modal-close").focus();
  }

  function closeTradeModal() {
    const backdrop = document.getElementById("trade-modal-backdrop");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    document.body.classList.remove("trade-modal-open");
    if (lastTradeFocused && typeof lastTradeFocused.focus === "function") lastTradeFocused.focus();
  }

  // ---------------------------------------------------------------------
  // Per-strategy performance - dashboard.json's periods[period].by_strategy
  // is computed server-side (site_data.py's summarize_period, from the
  // exact same confirmed-fill-sell definition every other number on this
  // page already uses) - this data existed already and simply had never
  // been rendered anywhere until now.
  // ---------------------------------------------------------------------
  const STRATEGY_LABELS = {
    rule_based: "Rule-Based (Stocks)",
    ml_filtered: "ML-Filtered (Stocks)",
    day_trading: "Day Trading (Crypto)",
  };

  function strategyCard(strategyKey, stats) {
    const label = STRATEGY_LABELS[strategyKey] || strategyKey;
    const avgPerTrade = stats.num_trades ? stats.realized_pnl_usd / stats.num_trades : null;
    return `
      <div class="strategy-card strategy-${strategyKey}">
        <div class="strategy-card-head"><span class="strategy-card-name">${label}</span></div>
        <div class="strategy-card-row"><span>Trades</span><span>${stats.num_trades}</span></div>
        <div class="strategy-card-row"><span>Win Rate</span><span>${stats.win_rate === null ? "—" : (stats.win_rate * 100).toFixed(0) + "%"}</span></div>
        <div class="strategy-card-row"><span>Avg P&amp;L / Trade</span><span class="${signClass(avgPerTrade)}">${avgPerTrade === null ? "—" : fmtUsdSigned(avgPerTrade)}</span></div>
        <div class="strategy-card-pnl ${signClass(stats.realized_pnl_usd)}">${fmtUsdSigned(stats.realized_pnl_usd)}</div>
      </div>`;
  }

  function renderStrategies(period) {
    const el = document.getElementById("strategy-cards");
    const labelEl = document.getElementById("strategy-period-label");
    if (!el || !dashboard) return;
    const p = dashboard.periods[period];
    if (labelEl) labelEl.textContent = p.label;
    const byStrategy = p.by_strategy || {};
    const keys = Object.keys(byStrategy);
    if (!keys.length) {
      el.innerHTML = '<p class="empty-state">No confirmed-fill sells in this period to attribute to a strategy yet.</p>';
      return;
    }
    // Ranked by realized P&L, highest first - "which strategy is
    // actually carrying the account" is a direct comparison, so lead
    // with the answer rather than a fixed/alphabetical order.
    keys.sort((a, b) => byStrategy[b].realized_pnl_usd - byStrategy[a].realized_pnl_usd);
    el.innerHTML = keys.map((k) => strategyCard(k, byStrategy[k])).join("");
  }

  // ---------------------------------------------------------------------
  // Backtest vs. Live - real walk-forward validation results
  // (site_data.py's build_strategy_backtest_comparison, reading
  // results/walk_forward/*.csv) compared against this account's own
  // real all-time trading numbers (dashboard.json's
  // periods.all_time.stocks_vs_crypto, computed the exact same way
  // every other number on this page already is). Deliberately NOT a
  // literal overlaid equity curve: no per-day backtest equity series is
  // stored anywhere to overlay against the live one, and fabricating
  // one would violate this whole site's own "nothing here is
  // simulated after the fact" promise (see the page's own subtitle).
  // This is instead a direct, honest stat comparison - the same real
  // evidence README.md's own "Current live status" section already
  // cites, shown next to what the account has actually done since its
  // last relaunch.
  // ---------------------------------------------------------------------
  const BACKTEST_ASSET_LABELS = { crypto: "Crypto — Day Trading", stock: "Stocks — Rule-Based" };

  function backtestCard(assetClass, bt, live) {
    const label = BACKTEST_ASSET_LABELS[assetClass] || assetClass;
    if (!bt || bt.available === false) {
      return `<div class="backtest-card"><div class="backtest-card-head"><span class="backtest-card-name">${label}</span></div><p class="empty-state">${(bt && bt.reason) || "Backtest validation data unavailable."}</p></div>`;
    }
    const liveRows = live
      ? `<div class="backtest-col-row"><span>Trades</span><span>${live.num_trades}</span></div>
         <div class="backtest-col-row"><span>Win Rate</span><span>${live.win_rate === null ? "—" : (live.win_rate * 100).toFixed(0) + "%"}</span></div>
         <div class="backtest-col-row"><span>Realized P&amp;L</span><span class="${signClass(live.realized_pnl_usd)}">${fmtUsdSigned(live.realized_pnl_usd)}</span></div>`
      : `<p class="empty-state">No confirmed live trades yet for this account.</p>`;
    return `
      <div class="backtest-card">
        <div class="backtest-card-head">
          <span class="backtest-card-name">${label}</span>
          <span class="backtest-card-config">${bt.config_label}</span>
        </div>
        <div class="backtest-compare">
          <div class="backtest-col">
            <h4>Backtested <span class="backtest-col-window">${bt.window_start} → ${bt.window_end}</span></h4>
            <div class="backtest-col-row"><span>Windows</span><span>${bt.num_traded_windows} traded of ${bt.num_windows} (${bt.num_tickers} tickers)</span></div>
            <div class="backtest-col-row"><span>Win Rate</span><span>${bt.win_rate === null ? "—" : (bt.win_rate * 100).toFixed(0) + "%"}</span></div>
            <div class="backtest-col-row"><span>Avg Return / Window</span><span class="${signClass(bt.avg_return_per_window)}">${fmtPct(bt.avg_return_per_window)}</span></div>
          </div>
          <div class="backtest-col">
            <h4>Live <span class="backtest-col-window">since last relaunch</span></h4>
            ${liveRows}
          </div>
        </div>
      </div>`;
  }

  function renderBacktestComparison() {
    const el = document.getElementById("backtest-cards");
    if (!el) return;
    if (!backtestComparison || !backtestComparison.available) {
      el.innerHTML = `<p class="empty-state">${(backtestComparison && backtestComparison.reason) || "Backtest comparison data wasn't generated for this run."}</p>`;
      return;
    }
    const allTime = dashboard && dashboard.periods && dashboard.periods.all_time;
    const liveByClass = (allTime && allTime.stocks_vs_crypto) || {};
    const classes = backtestComparison.classes || {};
    el.innerHTML = Object.keys(classes).map((k) => backtestCard(k, classes[k], liveByClass[k])).join("");
  }

  // ---------------------------------------------------------------------
  // Period switch (Today/Week/Month/All Time) + content tabs
  // (Overview/Positions/Trades) - two completely independent controls.
  // ---------------------------------------------------------------------
  function renderPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const active = btn.dataset.period === period;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    renderMetricRow(period);
    renderStatsGrid(period);
    safely("strategy breakdown", () => renderStrategies(period));
  }

  function switchContentTab(tab) {
    document.querySelectorAll(".content-tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".content-tab-panel").forEach((panel) => {
      panel.classList.toggle("is-active", panel.dataset.tabPanel === tab);
    });
  }

  // Runs `fn`, logging (not throwing) on failure - one section's data
  // being in an unexpected shape must never stop the rest of boot() from
  // running. A real bug once let exactly this happen: an exception
  // thrown while rendering positions/trades aborted the whole async
  // boot() function before it ever reached the code that attaches the
  // tab click-listeners below, leaving every tab silently dead with no
  // error visible on the page itself.
  function safely(label, fn) {
    try {
      fn();
    } catch (err) {
      console.error(`[investingbot] ${label} failed to render:`, err);
    }
  }

  async function boot() {
    // Tab wiring happens first and unconditionally, before any
    // data-dependent rendering - so the tabs are always clickable even
    // if dashboard.json is missing or a render function throws below.
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => renderPeriod(btn.dataset.period));
    });
    document.querySelectorAll(".content-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchContentTab(btn.dataset.tab));
    });

    // Trade History row clicks/keyboard-selects open the detail modal;
    // the filter box re-renders the table as the user types. Both wired
    // once here (the elements exist statically in the page markup) so
    // neither depends on trades.json having loaded yet.
    const ledgerBody = document.getElementById("ledger-body");
    if (ledgerBody) {
      ledgerBody.addEventListener("click", (e) => {
        const tr = e.target.closest("tr[data-trade-idx]");
        if (tr) openTradeModal(Number(tr.dataset.tradeIdx));
      });
      ledgerBody.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const tr = e.target.closest("tr[data-trade-idx]");
        if (!tr || tr !== document.activeElement) return;
        e.preventDefault();
        openTradeModal(Number(tr.dataset.tradeIdx));
      });
    }
    const ledgerFilterInput = document.getElementById("ledger-filter");
    if (ledgerFilterInput) {
      ledgerFilterInput.addEventListener("input", applyLedgerFilter);
    }

    // A nav link from charts.html points here with a hash (e.g.
    // index.html#positions) so a single click lands on the right tab -
    // without this, every such link always opened the default Overview
    // tab first, requiring a second click once already on this page.
    const hashTab = location.hash.slice(1);
    if (["overview", "positions", "tracker", "strategies", "backtest", "trades"].includes(hashTab)) {
      switchContentTab(hashTab);
    }

    [dashboard, positions, positionIndicators, tickerTracker, trades, equity, backtestComparison] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
      loadJson("position_indicators.json", { available: false, symbols: {} }),
      loadJson("ticker_tracker.json", { available: false, reason: "ticker_tracker.json not found", categories: { stocks: [], crypto: [] } }),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
      loadJson("backtest_comparison.json", { available: false, reason: "backtest_comparison.json not found", classes: {} }),
    ]);

    // Whatever happened above, the page is done with its initial load -
    // the CSS skeleton shimmer on empty containers only applies while
    // this class is present.
    document.body.classList.remove("is-loading");

    if (!dashboard) {
      document.getElementById("app").innerHTML =
        '<p class="empty-state" style="text-align:center;padding:60px 0;">' +
        "The dashboard data hasn't loaded yet - dashboard.json is missing or unreadable. " +
        "Once the update-dashboard workflow runs, this page will populate automatically.</p>";
      return;
    }

    safely("account strip", renderAccountStrip);
    safely("positions", renderPositions);
    safely("ticker tracker", renderTickerTracker);
    safely("trade history", renderLedger);
    safely("backtest comparison", renderBacktestComparison);
    safely("period metrics", () => renderPeriod(currentPeriod));

    // Just a text refresh, not animation - runs regardless of prefers-
    // reduced-motion. 30s is frequent enough that "(2m ago)" never
    // visibly sits wrong for long, without doing anything on every tick
    // beyond one Date.now() and a textContent write.
    setInterval(tickLastUpdatedRelative, 30000);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
