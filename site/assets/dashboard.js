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
  let trades = null;
  let currentPeriod = "today";  // controls the metric row + performance summary (period selector)

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
  const METRIC_DEFS = {
    equity: (p) => ({ text: fmtUsd(p.ending_value_usd), cls: "" }),
    period_pnl: (p) => ({ text: fmtUsdSigned(p.dollar_pnl_usd), cls: signClass(p.dollar_pnl_usd) }),
    pct_return: (p) => ({ text: fmtPct(p.pct_return), cls: signClass(p.pct_return) }),
    win_rate: (p) => ({ text: p.win_rate === null ? "—" : (p.win_rate * 100).toFixed(0) + "%", cls: "" }),
    num_trades: (p) => ({ text: String(p.num_trades ?? 0), cls: "" }),
    unrealized: (p) => ({ text: fmtUsdSigned(p.unrealized_pnl_usd), cls: signClass(p.unrealized_pnl_usd) }),
  };

  function setMetric(el, finalText, finalClass) {
    el.classList.remove("positive", "negative");
    const apply = () => {
      el.textContent = finalText;
      if (finalClass) el.classList.add(finalClass);
    };
    if (REDUCED_MOTION) { apply(); return; }
    el.style.opacity = "0";
    setTimeout(() => {
      apply();
      el.style.opacity = "1";
    }, 120);
  }

  function renderMetricRow(period) {
    const p = dashboard.periods[period];
    document.querySelectorAll(".metric-card[data-metric]").forEach((card) => {
      const key = card.dataset.metric;
      const def = METRIC_DEFS[key];
      if (!def) return;
      const { text, cls } = def(p);
      setMetric(card.querySelector("[data-value]"), text, cls);
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
  function renderAccountStrip() {
    const a = dashboard.account;
    document.getElementById("stat-cash").textContent = fmtUsd(a.cash_usd);
    document.getElementById("stat-buying-power").textContent = fmtUsd(a.buying_power_usd);
    document.getElementById("stat-equity").textContent = fmtUsd(a.equity_usd);
    document.getElementById("last-updated").textContent =
      `Last updated: ${fmtEt(dashboard.generated_at_utc)} (${dashboard.generated_at_utc} UTC)` +
      (a.available ? "" : " — live account figures unavailable this run, showing logged data only");
  }

  // ---------------------------------------------------------------------
  // Open positions
  // ---------------------------------------------------------------------
  function positionCard(p) {
    const pnl = p.unrealized_pl;
    const trend = pnl > 0 ? "trend-up" : pnl < 0 ? "trend-down" : "";
    const strategyLabel = p.strategy || "unknown";
    return `
      <div class="position-card ${trend}">
        <div class="position-card-head">
          <span class="position-card-ticker">${p.symbol}</span>
          <span class="position-card-strategy">${strategyLabel}</span>
        </div>
        <div class="position-card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="position-card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="position-card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="position-card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        <div class="position-card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPct(p.unrealized_plpc)})</div>
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

  function renderLedger() {
    const body = document.getElementById("ledger-body");
    const empty = document.getElementById("ledger-empty");
    if (!trades || !trades.available || !trades.trades.length) {
      body.innerHTML = "";
      empty.hidden = false;
      empty.textContent = "No trades logged yet.";
      return;
    }
    const rows = trades.trades; // already newest-first, capped server-side (site_data.py's MAX_TRADES_PUBLISHED)
    empty.hidden = true;
    body.innerHTML = rows.map((t) => {
      const pnlCls = t.realized_pnl_usd === null ? "" : (t.realized_pnl_usd >= 0 ? "pnl-positive" : "pnl-negative");
      const qtyOrNotional = t.notional_usd !== null ? fmtUsd(t.notional_usd) : fmtQty(t.position_qty_before);
      return `<tr>
        <td>${fmtEt(t.timestamp_utc)}</td>
        <td>${t.asset_class}</td>
        <td>${t.ticker}</td>
        <td>${t.strategy}</td>
        <td>${t.action}</td>
        <td>${fmtUsd(t.price_usd)}${t.price_is_confirmed_fill ? "" : " (est.)"}</td>
        <td>${qtyOrNotional}</td>
        <td class="${pnlCls}">${t.realized_pnl_usd === null ? "—" : fmtUsdSigned(t.realized_pnl_usd)}</td>
        <td><span class="badge ${STATUS_BADGE_CLASS[t.order_status] || ""}">${STATUS_LABEL[t.order_status] || t.order_status}</span></td>
        <td>${t.notes || ""}</td>
      </tr>`;
    }).join("");
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

    // A nav link from charts.html points here with a hash (e.g.
    // index.html#positions) so a single click lands on the right tab -
    // without this, every such link always opened the default Overview
    // tab first, requiring a second click once already on this page.
    const hashTab = location.hash.slice(1);
    if (["overview", "positions", "trades"].includes(hashTab)) {
      switchContentTab(hashTab);
    }

    [dashboard, positions, trades] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
      loadJson("trades.json", { available: false, trades: [] }),
    ]);

    if (!dashboard) {
      document.getElementById("app").innerHTML =
        '<p class="empty-state" style="text-align:center;padding:60px 0;">' +
        "The dashboard data hasn't loaded yet - dashboard.json is missing or unreadable. " +
        "Once the update-dashboard workflow runs, this page will populate automatically.</p>";
      return;
    }

    safely("account strip", renderAccountStrip);
    safely("positions", renderPositions);
    safely("trade history", renderLedger);
    safely("period metrics", () => renderPeriod(currentPeriod));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
