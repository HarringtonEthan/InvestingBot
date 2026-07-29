/*
 * Ethan's Market Casino - dedicated charts page (charts.html).
 *
 * Split out of dashboard.js so the main dashboard page never has to load
 * Chart.js or render eight canvases just to show the slot machines and
 * open positions - the unbounded-canvas-height bug (see .chart-canvas-wrap
 * in styles.css) plus keeping Chart.js off the main page were both real
 * contributors to page lag. This file owns every chart and nothing else:
 * no fireworks, no panda intro, no positions/ledger rendering.
 */

(function () {
  "use strict";

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let dashboard = null;
  let trades = null;
  let equity = null;
  let chartPeriod = "today";
  let charts = {};

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

  function fmtUsd(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

  // Every time-series chart on this page used to label every single
  // data point (a new equity/trade row every few minutes), which meant
  // dozens of overlapping timestamps crammed along the x-axis - close
  // to unreadable. maxTicksLimit + autoSkip let Chart.js pick a sane,
  // evenly-spaced subset instead of trying to cram all of them in.
  function baseChartOptions(extra) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: CASINO_COLORS.cream } },
      },
      scales: {
        x: {
          ticks: { color: CASINO_COLORS.cream, maxTicksLimit: 7, autoSkip: true, maxRotation: 40, minRotation: 0 },
          grid: { color: "rgba(255,215,0,0.08)" },
        },
        // beginAtZero matters for every chart on this page: they're all
        // either counts (wins/losses - naturally 0-based) or a value
        // measured *relative to* a baseline (net gain/loss, cumulative
        // P&L, drawdown, strategy comparison) where 0 is the meaningful
        // reference point. Without this, Chart.js can auto-scale the
        // y-axis to NOT start at 0, which visually exaggerates the
        // difference between bars/lines that are actually close in real
        // magnitude.
        y: { beginAtZero: true, ticks: { color: CASINO_COLORS.cream }, grid: { color: "rgba(255,215,0,0.08)" } },
      },
      animation: REDUCED_MOTION ? false : undefined,
    }, extra || {});
  }

  // Shows a helpful explanation instead of a blank chart card whenever
  // there's genuinely nothing to plot yet (e.g. no closed trades this
  // period) - mirrors what the PNG dashboard (visualize_log.py) already
  // does for the same situation, rather than leaving empty axes.
  function setChartEmptyState(chartId, message) {
    const wrap = document.getElementById(chartId + "-wrap");
    const empty = document.getElementById(chartId + "-empty");
    const isEmpty = message !== null;
    if (wrap) wrap.hidden = isEmpty;
    if (empty) {
      empty.hidden = !isEmpty;
      if (isEmpty) empty.innerHTML = message;
    }
  }

  function unrealizedNote(period, assetClass) {
    const p = dashboard.periods[period];
    const value = assetClass
      ? (p.unrealized_pnl_by_asset_class || {})[assetClass]
      : p.unrealized_pnl_usd;
    if (value === null || value === undefined) return "";
    const cls = value >= 0 ? "positive" : "negative";
    const sign = value >= 0 ? "+" : "-";
    const amount = sign + "$" + Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `<p class="chart-empty-note ${cls}">Live unrealized P&amp;L right now (open positions): ${amount}</p>`;
  }

  // Confirmed-fill SELLs within a period's window, optionally restricted
  // to one asset class, oldest first. Mirrors site_data.py's own
  // is_confirmed_sell definition exactly (action === "SELL" and
  // order_status === "confirmed_fill") so a client-side chart can never
  // disagree with the server-computed realized_pnl_usd figures.
  function confirmedSellsForPeriod(period, assetClass) {
    if (!trades || !trades.available) return [];
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const endMs = p.end_utc ? new Date(p.end_utc).getTime() : Infinity;
    return trades.trades
      .filter((t) => {
        if (t.action !== "SELL" || t.order_status !== "confirmed_fill" || t.realized_pnl_usd === null) return false;
        if (assetClass && t.asset_class !== assetClass) return false;
        const ts = new Date(t.timestamp_utc).getTime();
        return ts >= startMs && ts <= endMs;
      })
      .sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  }

  function renderNetGainLossChart(period) {
    const canvas = document.getElementById("chart-net-gain-loss");
    if (typeof Chart === "undefined") return;
    destroyChart("netGainLoss");
    const p = dashboard.periods[period];
    if (!equity || !equity.available || !equity.points.length || p.starting_value_usd === null) {
      setChartEmptyState("chart-net-gain-loss", "No equity history logged yet for this period.");
      return;
    }
    const baseline = p.starting_value_usd;
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    if (!points.length) {
      setChartEmptyState("chart-net-gain-loss", "No equity history logged yet for this period.");
      return;
    }
    setChartEmptyState("chart-net-gain-loss", null);
    const labels = points.map((pt) => fmtEt(pt.timestamp_utc));
    const values = points.map((pt) => pt.portfolio_value_usd - baseline);
    const finalPositive = values[values.length - 1] >= 0;
    charts.netGainLoss = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: `Net gain/loss vs. ${fmtUsd(baseline)} baseline ($)`,
          data: values,
          borderColor: finalPositive ? CASINO_COLORS.green : CASINO_COLORS.red,
          backgroundColor: finalPositive ? "rgba(57,255,20,0.15)" : "rgba(255,59,59,0.15)",
          fill: true,
          tension: 0.2,
          pointRadius: 0,
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderCumulativePnlChart(period, assetClass, canvasId, chartKey, color) {
    const canvas = document.getElementById(canvasId);
    if (typeof Chart === "undefined") return;
    destroyChart(chartKey);
    const sells = confirmedSellsForPeriod(period, assetClass);
    if (!sells.length) {
      const label = assetClass === "crypto" ? "Crypto" : "Stock";
      setChartEmptyState(canvasId, `<p>No executed ${label} SELL trades yet this period.</p>${unrealizedNote(period, assetClass)}`);
      return;
    }
    setChartEmptyState(canvasId, null);
    let running = 0;
    const points = sells.map((t) => {
      running += t.realized_pnl_usd;
      return { x: fmtEt(t.timestamp_utc), y: running };
    });
    charts[chartKey] = new Chart(canvas, {
      type: "line",
      data: {
        labels: points.map((pt) => pt.x),
        datasets: [{
          label: "Cumulative realized P&L ($)",
          data: points.map((pt) => pt.y),
          borderColor: color,
          backgroundColor: "transparent",
          stepped: "after", // matches the old PNG dashboard's step chart, not a smoothed line
          pointRadius: 3,
          pointBackgroundColor: color,
        }],
      },
      options: baseChartOptions(),
    });
  }

  function renderWinLossPerTickerChart(period, assetClass, canvasId, chartKey) {
    const canvas = document.getElementById(canvasId);
    if (typeof Chart === "undefined") return;
    destroyChart(chartKey);
    const sells = confirmedSellsForPeriod(period, assetClass);
    if (!sells.length) {
      const label = assetClass === "crypto" ? "Crypto" : "Stock";
      setChartEmptyState(canvasId, `<p>No executed ${label} SELL trades yet this period.</p>${unrealizedNote(period, assetClass)}`);
      return;
    }
    setChartEmptyState(canvasId, null);
    const tickers = Array.from(new Set(sells.map((t) => t.ticker))).sort();
    const wins = tickers.map((tk) => sells.filter((t) => t.ticker === tk && t.realized_pnl_usd > 0).length);
    const losses = tickers.map((tk) => sells.filter((t) => t.ticker === tk && t.realized_pnl_usd <= 0).length);
    charts[chartKey] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: tickers,
        datasets: [
          { label: "Wins", data: wins, backgroundColor: CASINO_COLORS.green },
          { label: "Losses", data: losses, backgroundColor: CASINO_COLORS.red },
        ],
      },
      options: baseChartOptions({
        scales: {
          x: { stacked: true, ticks: { color: CASINO_COLORS.cream }, grid: { color: "rgba(255,215,0,0.08)" } },
          y: { stacked: true, beginAtZero: true, ticks: { color: CASINO_COLORS.cream, precision: 0 }, grid: { color: "rgba(255,215,0,0.08)" } },
        },
      }),
    });
  }

  function renderDailyPnlChart(period) {
    const canvas = document.getElementById("chart-daily-pnl");
    if (typeof Chart === "undefined") return;
    if (!equity || !equity.available || equity.points.length < 2) {
      setChartEmptyState("chart-daily-pnl", "<p>Not enough days logged yet to show day-over-day P&amp;L - needs at least 2 calendar days of equity history.</p>");
      return;
    }
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    // Bucket equity points by ET calendar day, using each day's last
    // known value, then diff day-over-day.
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
    if (!dailyPnl.length) {
      setChartEmptyState("chart-daily-pnl", "<p>Not enough days logged yet to show day-over-day P&amp;L - needs at least 2 calendar days of equity history.</p>");
      return;
    }
    setChartEmptyState("chart-daily-pnl", null);
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
    if (typeof Chart === "undefined") return;
    if (!equity || !equity.available || equity.points.length < 2) {
      setChartEmptyState("chart-drawdown", "<p>Not enough equity history logged yet to compute drawdown.</p>");
      return;
    }
    const p = dashboard.periods[period];
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const points = equity.points.filter((pt) => new Date(pt.timestamp_utc).getTime() >= startMs);
    destroyChart("drawdown");
    if (points.length < 2) {
      setChartEmptyState("chart-drawdown", "<p>Not enough equity history logged yet this period to compute drawdown.</p>");
      return;
    }
    setChartEmptyState("chart-drawdown", null);
    let peak = points[0].portfolio_value_usd;
    const drawdowns = points.map((pt) => {
      peak = Math.max(peak, pt.portfolio_value_usd);
      return peak > 0 ? (pt.portfolio_value_usd - peak) / peak : 0;
    });
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

  function renderStrategyChart(period) {
    const canvas = document.getElementById("chart-strategy");
    if (typeof Chart === "undefined") return;
    const p = dashboard.periods[period];
    const entries = Object.entries(p.by_strategy || {});
    destroyChart("strategy");
    if (!entries.length) {
      setChartEmptyState("chart-strategy", `<p>No closed trades yet for any strategy this period.</p>${unrealizedNote(period, null)}`);
      return;
    }
    setChartEmptyState("chart-strategy", null);
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

  function renderChartsForPeriod(period) {
    renderNetGainLossChart(period);
    renderCumulativePnlChart(period, "crypto", "chart-crypto-cum-pnl", "cryptoCumPnl", CASINO_COLORS.pink);
    renderCumulativePnlChart(period, "stock", "chart-stock-cum-pnl", "stockCumPnl", CASINO_COLORS.purple);
    renderWinLossPerTickerChart(period, "crypto", "chart-crypto-winloss", "cryptoWinLoss");
    renderWinLossPerTickerChart(period, "stock", "chart-stock-winloss", "stockWinLoss");
    renderDailyPnlChart(period);
    renderDrawdownChart(period);
    renderStrategyChart(period);
  }

  async function boot() {
    [dashboard, trades, equity] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
    ]);

    if (!dashboard) {
      document.getElementById("charts-app").innerHTML =
        '<p class="empty-state" style="text-align:center;padding:60px 0;">' +
        "🎰 The house data hasn't loaded yet - dashboard.json is missing or unreadable. " +
        "Once the update-dashboard workflow runs, this page will populate automatically.</p>";
      return;
    }

    document.getElementById("last-updated").textContent =
      `Last updated: ${fmtEt(dashboard.generated_at_utc)} (${dashboard.generated_at_utc} UTC)`;

    const chartPeriodSelect = document.getElementById("chart-period-select");
    if (chartPeriodSelect) {
      chartPeriodSelect.value = chartPeriod;
      chartPeriodSelect.addEventListener("change", () => {
        chartPeriod = chartPeriodSelect.value;
        renderChartsForPeriod(chartPeriod);
      });
    }

    renderChartsForPeriod(chartPeriod);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
