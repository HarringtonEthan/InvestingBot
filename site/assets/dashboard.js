/*
 * Ethan's Market Casino - dashboard frontend.
 *
 * Loads the JSON files site_data.py generates (data/dashboard.json,
 * positions.json, trades.json, equity.json) and renders them. Every
 * fetch is wrapped so a missing, empty, or malformed file degrades to a
 * clearly-labeled empty state instead of a broken page or a console
 * error the visitor never sees. Nothing here fabricates a number - if a
 * file didn't load, the corresponding widget says so.
 */

(function () {
  "use strict";

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let dashboard = null;
  let positions = null;
  let trades = null;
  let currentPeriod = "today";  // controls the slot machines + stats grid (top pill-tabs)

  // ---------------------------------------------------------------------
  // Safe fetch: never throws, never lets one bad file break the others.
  // ---------------------------------------------------------------------
  async function loadJson(name, fallback) {
    try {
      const res = await fetch(DATA_BASE + name, { cache: "no-store" });
      if (!res.ok) {
        console.warn(`[casino] ${name} responded with HTTP ${res.status} - using fallback.`);
        return fallback;
      }
      const text = await res.text();
      if (!text || !text.trim()) {
        console.warn(`[casino] ${name} was empty - using fallback.`);
        return fallback;
      }
      try {
        return JSON.parse(text);
      } catch (parseErr) {
        console.warn(`[casino] ${name} was malformed JSON - using fallback.`, parseErr);
        return fallback;
      }
    } catch (networkErr) {
      console.warn(`[casino] ${name} could not be fetched (offline? missing file?) - using fallback.`, networkErr);
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
  // Slot machines
  // ---------------------------------------------------------------------
  const SLOT_DEFS = {
    equity: (p) => ({ text: fmtUsd(p.ending_value_usd), cls: "" }),
    period_pnl: (p) => ({ text: fmtUsdSigned(p.dollar_pnl_usd), cls: signClass(p.dollar_pnl_usd) }),
    pct_return: (p) => ({ text: fmtPct(p.pct_return), cls: signClass(p.pct_return) }),
    win_rate: (p) => ({ text: p.win_rate === null ? "—" : (p.win_rate * 100).toFixed(0) + "%", cls: "" }),
    num_trades: (p) => ({ text: String(p.num_trades ?? 0), cls: "" }),
    unrealized: (p) => ({ text: fmtUsdSigned(p.unrealized_pnl_usd), cls: signClass(p.unrealized_pnl_usd) }),
  };

  function spinSlot(el, finalText, finalClass) {
    el.classList.remove("positive", "negative");
    if (REDUCED_MOTION) {
      el.textContent = finalText;
      if (finalClass) el.classList.add(finalClass);
      return;
    }
    el.classList.add("spinning");
    const scrambleChars = "0123456789$%+-.,";
    let ticks = 0;
    const maxTicks = 10;
    const interval = setInterval(() => {
      ticks += 1;
      if (ticks >= maxTicks) {
        clearInterval(interval);
        el.classList.remove("spinning");
        el.textContent = finalText;
        if (finalClass) el.classList.add(finalClass);
        return;
      }
      let scrambled = "";
      for (let i = 0; i < Math.max(3, finalText.length); i++) {
        scrambled += scrambleChars[Math.floor(Math.random() * scrambleChars.length)];
      }
      el.textContent = scrambled;
    }, 45);
  }

  function renderSlots(period) {
    const p = dashboard.periods[period];
    document.querySelectorAll(".slot-machine").forEach((machine) => {
      const key = machine.dataset.slot;
      const def = SLOT_DEFS[key];
      if (!def) return;
      const { text, cls } = def(p);
      const reel = machine.querySelector("[data-reel]");
      spinSlot(reel, text, cls);
    });
  }

  // ---------------------------------------------------------------------
  // Stats grid
  // ---------------------------------------------------------------------
  function statTile(label, value, opts) {
    opts = opts || {};
    const cls = opts.cls || "";
    const sub = opts.sub ? `<div class="sub">${opts.sub}</div>` : "";
    return `<div class="stat-tile"><div class="label">${label}</div><div class="value ${cls}">${value}</div>${sub}</div>`;
  }

  function renderStatsGrid(period) {
    const p = dashboard.periods[period];
    document.getElementById("period-label").textContent = p.label;
    const startNote = p.starting_value_is_first_available
      ? "first value logged in this period (no earlier data to carry forward)"
      : (p.start_utc ? `as of ${fmtEt(p.start_utc)}` : "start of all logged history");

    const tiles = [
      statTile("Starting Value", fmtUsd(p.starting_value_usd), { sub: startNote }),
      statTile("Ending Value", fmtUsd(p.ending_value_usd)),
      statTile("Dollar P&amp;L", fmtUsdSigned(p.dollar_pnl_usd), { cls: signClass(p.dollar_pnl_usd) }),
      statTile("% Return", fmtPct(p.pct_return), { cls: signClass(p.pct_return) }),
      statTile("Realized P&amp;L", fmtUsdSigned(p.realized_pnl_usd), { cls: signClass(p.realized_pnl_usd) }),
      statTile("Unrealized P&amp;L", fmtUsdSigned(p.unrealized_pnl_usd), { cls: signClass(p.unrealized_pnl_usd) }),
      statTile("Trades (closed)", p.num_trades, { sub: `${p.num_buys ?? 0} buys, ${p.num_unconfirmed ?? 0} unconfirmed, ${p.num_not_placed ?? 0} not placed` }),
      statTile("Winning Trades", p.num_wins),
      statTile("Losing Trades", p.num_losses),
      statTile("Win Rate", p.win_rate === null ? "—" : (p.win_rate * 100).toFixed(1) + "%"),
      statTile("Best Trade", p.best_trade ? `${p.best_trade.ticker} ${fmtUsdSigned(p.best_trade.realized_pnl_usd)}` : "—", { cls: p.best_trade ? "positive" : "" }),
      statTile("Worst Trade", p.worst_trade ? `${p.worst_trade.ticker} ${fmtUsdSigned(p.worst_trade.realized_pnl_usd)}` : "—", { cls: p.worst_trade ? "negative" : "" }),
      statTile("Max Drawdown", p.max_drawdown === null ? "not enough data" : fmtPct(p.max_drawdown), { cls: p.max_drawdown ? "negative" : "" }),
    ];
    document.getElementById("stats-grid").innerHTML = tiles.join("");

    document.getElementById("methodology-note").innerHTML =
      `📜 <strong>How this is calculated:</strong> ${dashboard.methodology.baseline}. ${dashboard.methodology.num_trades}`;

    const resetNote = document.getElementById("reset-note");
    if (resetNote) {
      // Trade logs get archived and restarted fresh on a same-day
      // relaunch, but the equity log never resets - so a period's
      // Starting/Ending Value can straddle the relaunch while Realized
      // P&L only counts trades since it. When that happens, Dollar P&L
      // legitimately won't match Realized + Unrealized - it's not a bug,
      // it's two numbers describing different eras of the account. See
      // site_data.py's summarize_period() for the exact detection logic.
      resetNote.hidden = !p.trade_log_reset_during_period;
    }
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
  // Blackjack table (positions)
  // ---------------------------------------------------------------------
  const SUITS = { crypto: "♦ ♦", stock: "♠ ♣" };

  function positionCard(p) {
    const pnl = p.unrealized_pl;
    const glow = pnl > 0 ? "glow-win" : pnl < 0 ? "glow-loss" : "glow-neutral";
    const suit = SUITS[p.is_crypto ? "crypto" : "stock"];
    const strategyLabel = p.strategy || "unknown";
    // Strategy used to render as a "card-strategy" strip pinned to the
    // bottom of the card, which overlapped the dollar amount above it and
    // made it unreadable. It's still available on hover via title -
    // just not painted on top of the numbers anymore.
    return `
      <div class="playing-card ${glow}" title="Strategy: ${strategyLabel}">
        <div class="card-corner">${p.symbol}</div>
        <div class="card-suit">${suit}</div>
        <div class="card-ticker">${p.symbol}</div>
        <div class="card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        <div class="card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPct(p.unrealized_plpc)})</div>
        <div class="card-strategy-tag">${strategyLabel}</div>
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
  // Ledger (past trades) - deliberately NOT filtered by the top pill-tabs
  // period control (or by the charts page's own period dropdown, which
  // lives entirely on charts.html now): this section is meant to always
  // show the most recent real history regardless of whatever period the
  // rest of the page is currently scoped to.
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
      empty.textContent = "No trades logged yet — the house is waiting.";
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
  // Period switch + boot
  // ---------------------------------------------------------------------
  // Controls the slot machines + stats grid only. The charts now live on
  // their own page (charts.html / assets/charts.js) - splitting them out
  // keeps Chart.js and eight canvases off the main dashboard entirely,
  // which was a real source of page lag.
  function renderPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const active = btn.dataset.period === period;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    renderSlots(period);
    renderStatsGrid(period);
  }

  // ---------------------------------------------------------------------
  // Content tabs (Stats / Positions / Past Trades) - a completely
  // separate concept from the Today/Week/Month/All-Time period pills
  // above: this just controls which section of the page is visible, so
  // visitors pick one thing to look at instead of scrolling past
  // everything else to find it.
  // ---------------------------------------------------------------------
  function switchContentTab(tab) {
    document.querySelectorAll(".content-tab-btn").forEach((btn) => {
      const active = btn.dataset.tab === tab;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".content-tab-panel").forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== tab;
    });
  }

  async function boot() {
    [dashboard, positions, trades] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
      loadJson("trades.json", { available: false, trades: [] }),
    ]);

    if (!dashboard) {
      document.getElementById("app").innerHTML =
        '<p class="empty-state" style="text-align:center;padding:60px 0;">' +
        "🎰 The house data hasn't loaded yet - dashboard.json is missing or unreadable. " +
        "Once the update-dashboard workflow runs, this page will populate automatically.</p>";
      return;
    }

    renderAccountStrip();
    renderPositions();
    renderLedger();

    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => renderPeriod(btn.dataset.period));
    });
    document.querySelectorAll(".content-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchContentTab(btn.dataset.tab));
    });

    renderPeriod(currentPeriod);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
