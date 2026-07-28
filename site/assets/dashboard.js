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
  let equity = null;
  let currentPeriod = "today";
  let charts = {};

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
    return `
      <div class="playing-card ${glow}">
        <div class="card-corner">${p.symbol}</div>
        <div class="card-suit">${suit}</div>
        <div class="card-ticker">${p.symbol}</div>
        <div class="card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        <div class="card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPct(p.unrealized_plpc)})</div>
        <div class="card-strategy">${p.strategy || "strategy: unknown"}</div>
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
  // Ledger (recent trades), filtered to the selected period's window
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

  function renderLedger(period) {
    const body = document.getElementById("ledger-body");
    const empty = document.getElementById("ledger-empty");
    if (!trades || !trades.available || !trades.trades.length) {
      body.innerHTML = "";
      empty.hidden = false;
      return;
    }
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const endMs = p.end_utc ? new Date(p.end_utc).getTime() : Infinity;
    const rows = trades.trades.filter((t) => {
      const ts = new Date(t.timestamp_utc).getTime();
      return ts >= startMs && ts <= endMs;
    });
    if (!rows.length) {
      body.innerHTML = "";
      empty.hidden = false;
      empty.textContent = `No trades logged for ${p.label.toLowerCase()} yet.`;
      return;
    }
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
  // Charts
  // ---------------------------------------------------------------------
  const CASINO_COLORS = {
    gold: "#ffd700",
    green: "#39ff14",
    red: "#ff3b3b",
    purple: "#a259ff",
    pink: "#ff2fb0",
    cream: "#f3e6c8",
  };

  function destroyChart(key) {
    if (charts[key]) {
      charts[key].destroy();
      delete charts[key];
    }
  }

  function baseChartOptions(extra) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: CASINO_COLORS.cream } },
      },
      scales: {
        x: { ticks: { color: CASINO_COLORS.cream }, grid: { color: "rgba(255,215,0,0.08)" } },
        y: { ticks: { color: CASINO_COLORS.cream }, grid: { color: "rgba(255,215,0,0.08)" } },
      },
      animation: REDUCED_MOTION ? false : undefined,
    }, extra || {});
  }

  function renderEquityChart(period) {
    const canvas = document.getElementById("chart-equity");
    if (typeof Chart === "undefined" || !equity || !equity.available || !equity.points.length) {
      return;
    }
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    const labels = points.map((pt) => fmtEt(pt.timestamp_utc));
    const values = points.map((pt) => pt.portfolio_value_usd);

    destroyChart("equity");
    charts.equity = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Account Value ($)",
          data: values,
          borderColor: CASINO_COLORS.gold,
          backgroundColor: "rgba(255,215,0,0.15)",
          fill: true,
          tension: 0.25,
          pointRadius: 0,
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderDailyPnlChart(period) {
    const canvas = document.getElementById("chart-daily-pnl");
    if (typeof Chart === "undefined" || !equity || !equity.available || equity.points.length < 2) return;
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    // Bucket equity points by ET calendar day, using each day's last
    // known value, then diff day-over-day - a simple, honest reading of
    // "how much did the account gain or lose that day."
    const byDay = new Map();
    points.forEach((pt) => {
      const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(pt.timestamp_utc));
      byDay.set(dayKey, pt.portfolio_value_usd);
    });
    const days = Array.from(byDay.keys()).sort();
    const dailyPnl = [];
    for (let i = 1; i < days.length; i++) {
      dailyPnl.push({ day: days[i], pnl: byDay.get(days[i]) - byDay.get(days[i - 1]) });
    }
    destroyChart("dailyPnl");
    if (!dailyPnl.length) return;
    charts.dailyPnl = new Chart(canvas, {
      type: "bar",
      data: {
        labels: dailyPnl.map((d) => d.day),
        datasets: [{
          label: "Daily P&L ($)",
          data: dailyPnl.map((d) => d.pnl),
          backgroundColor: dailyPnl.map((d) => (d.pnl >= 0 ? CASINO_COLORS.green : CASINO_COLORS.red)),
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderDrawdownChart(period) {
    const canvas = document.getElementById("chart-drawdown");
    if (typeof Chart === "undefined" || !equity || !equity.available || equity.points.length < 2) return;
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    if (points.length < 2) { destroyChart("drawdown"); return; }
    let peak = points[0].portfolio_value_usd;
    const drawdowns = points.map((pt) => {
      peak = Math.max(peak, pt.portfolio_value_usd);
      return peak > 0 ? (pt.portfolio_value_usd - peak) / peak : 0;
    });
    destroyChart("drawdown");
    charts.drawdown = new Chart(canvas, {
      type: "line",
      data: {
        labels: points.map((pt) => fmtEt(pt.timestamp_utc)),
        datasets: [{
          label: "Drawdown (%)",
          data: drawdowns.map((d) => d * 100),
          borderColor: CASINO_COLORS.red,
          backgroundColor: "rgba(255,59,59,0.15)",
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderAssetClassChart(period) {
    const canvas = document.getElementById("chart-asset-class");
    if (typeof Chart === "undefined") return;
    const p = dashboard.periods[period];
    const stock = (p.stocks_vs_crypto.stock || {}).realized_pnl_usd || 0;
    const crypto = (p.stocks_vs_crypto.crypto || {}).realized_pnl_usd || 0;
    destroyChart("assetClass");
    charts.assetClass = new Chart(canvas, {
      type: "bar",
      data: {
        labels: ["Stocks", "Crypto"],
        datasets: [{
          label: "Realized P&L ($)",
          data: [stock, crypto],
          backgroundColor: [CASINO_COLORS.purple, CASINO_COLORS.pink],
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderStrategyChart(period) {
    const canvas = document.getElementById("chart-strategy");
    if (typeof Chart === "undefined") return;
    const p = dashboard.periods[period];
    const entries = Object.entries(p.by_strategy || {});
    destroyChart("strategy");
    if (!entries.length) return;
    charts.strategy = new Chart(canvas, {
      type: "bar",
      data: {
        labels: entries.map(([k]) => k),
        datasets: [{
          label: "Realized P&L ($)",
          data: entries.map(([, v]) => v.realized_pnl_usd),
          backgroundColor: CASINO_COLORS.gold,
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderWinLossChart(period) {
    const canvas = document.getElementById("chart-winloss");
    if (typeof Chart === "undefined") return;
    const p = dashboard.periods[period];
    destroyChart("winLoss");
    if (!p.num_trades) return;
    charts.winLoss = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["Wins", "Losses"],
        datasets: [{
          data: [p.num_wins, p.num_losses],
          backgroundColor: [CASINO_COLORS.green, CASINO_COLORS.red],
          borderColor: CASINO_COLORS.gold,
        }],
      },
      options: baseChartOptions({ scales: undefined }),
    });
  }

  function renderCharts(period) {
    renderEquityChart(period);
    renderDailyPnlChart(period);
    renderDrawdownChart(period);
    renderAssetClassChart(period);
    renderStrategyChart(period);
    renderWinLossChart(period);
  }

  // ---------------------------------------------------------------------
  // Period switch + boot
  // ---------------------------------------------------------------------
  function renderPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const active = btn.dataset.period === period;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
    renderSlots(period);
    renderStatsGrid(period);
    renderLedger(period);
    renderCharts(period);
  }

  async function boot() {
    [dashboard, positions, trades, equity] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
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

    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => renderPeriod(btn.dataset.period));
    });

    renderPeriod(currentPeriod);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
