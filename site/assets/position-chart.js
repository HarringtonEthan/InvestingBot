/*
 * Shared "price since purchase" modal for position cards - loaded by
 * both index.html (Positions tab) and charts.html (positions panels).
 * Listens for clicks/keypresses on any element carrying a data-symbol
 * attribute via delegation on `document`, so it works regardless of
 * whether dashboard.js or charts.js rendered the card, and regardless of
 * when (asynchronously, via innerHTML) that card was inserted - no need
 * to coordinate boot order with either page's own renderer.
 *
 * Reads site/data/position_history.json - real Alpaca historical prices
 * this project's own site_data.py already fetched server-side, never
 * fabricated here. A symbol with no data yet (feature not enabled for
 * this run, a per-symbol fetch failure, too few points) shows an honest
 * message instead of a chart - see the state handling in openModal().
 */

(function () {
  "use strict";

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLORS = { green: "#34d372", red: "#f0554a", text: "#9aa5a0", grid: "rgba(255,255,255,0.06)" };

  let historyData = null;
  let historyPromise = null;
  let chart = null;
  let lastFocused = null;
  let currentEntryPrice = null;
  let currentSymbolLabel = "";
  let currentSeries = [];

  // ---------------------------------------------------------------------
  // Data loading - independent of dashboard.js/charts.js's own fetches,
  // keeps this feature fully decoupled from either page's renderer.
  // ---------------------------------------------------------------------
  function loadHistory() {
    if (historyPromise) return historyPromise;
    historyPromise = fetch("data/position_history.json", { cache: "no-store" })
      .then((res) => (res.ok ? res.text() : ""))
      .then((text) => {
        if (!text || !text.trim()) return { available: false, symbols: {} };
        try {
          return JSON.parse(text);
        } catch (e) {
          return { available: false, symbols: {} };
        }
      })
      .catch(() => ({ available: false, symbols: {} }))
      .then((data) => {
        historyData = data;
        return data;
      });
    return historyPromise;
  }

  // ---------------------------------------------------------------------
  // Formatting - small local copies, same convention dashboard.js and
  // charts.js each already keep their own rather than sharing a module.
  // ---------------------------------------------------------------------
  function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
  function fmtPrice(v) {
    if (!isNum(v)) return "—";
    const decimals = Math.abs(v) < 1 ? 6 : 2;
    return "$" + v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }
  function fmtDateET(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric" }).format(d);
  }
  function fmtDateTimeET(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    const datePart = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric" }).format(d);
    const timePart = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true }).format(d);
    return `${datePart} at ${timePart} ET`;
  }
  function fmtAxisDate(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric" }).format(d);
  }

  // ---------------------------------------------------------------------
  // Custom tooltip + crosshair - reuses the exact #chart-tooltip element
  // and CSS classes charts.html's own charts already use (created here
  // if the current page doesn't already declare one, e.g. index.html),
  // so a position's price chart looks and behaves like the account
  // performance chart's, per the same visual language sitewide.
  // ---------------------------------------------------------------------
  function tooltipEl() {
    let el = document.getElementById("chart-tooltip");
    if (!el) {
      el = document.createElement("div");
      el.id = "chart-tooltip";
      el.setAttribute("role", "tooltip");
      el.setAttribute("aria-hidden", "true");
      document.body.appendChild(el);
    }
    return el;
  }
  function hideTooltip() {
    const el = document.getElementById("chart-tooltip");
    if (!el) return;
    el.classList.remove("is-visible");
    el.setAttribute("aria-hidden", "true");
  }
  function externalTooltip(ctx) {
    const el = tooltipEl();
    const model = ctx.tooltip;
    if (!model || model.opacity === 0) { hideTooltip(); return; }
    const idx = model.dataPoints && model.dataPoints.length ? model.dataPoints[0].dataIndex : null;
    if (idx === null || idx === undefined) return;
    const point = currentSeries[idx];
    if (!point) return;
    const pct = currentEntryPrice ? ((point.price / currentEntryPrice) - 1) * 100 : null;

    let html = `<div class="tt-title">${currentSymbolLabel}</div>`;
    html += `<div class="tt-time">${fmtDateTimeET(point.t)}</div>`;
    html += `<div class="tt-rows">`;
    html += `<div class="tt-row"><span class="tt-label">Price</span><span class="tt-val">${fmtPrice(point.price)}</span></div>`;
    if (isNum(pct)) {
      html += `<div class="tt-row"><span class="tt-label">Since purchase</span><span class="tt-val ${pct >= 0 ? "positive" : "negative"}">${(pct >= 0 ? "+" : "") + pct.toFixed(2)}%</span></div>`;
    }
    html += `</div>`;
    el.innerHTML = html;
    el.style.borderColor = isNum(pct) ? (pct >= 0 ? COLORS.green : COLORS.red) : "";
    el.setAttribute("aria-hidden", "false");
    el.classList.add("is-visible");

    const rect = ctx.chart.canvas.getBoundingClientRect();
    const w = el.offsetWidth, h = el.offsetHeight;
    let left = rect.left + model.caretX + 14;
    let top = rect.top + model.caretY - h / 2;
    if (left + w > window.innerWidth - 8) left = rect.left + model.caretX - w - 14;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    if (top + h > window.innerHeight - 8) top = window.innerHeight - h - 8;
    el.style.left = left + "px";
    el.style.top = top + "px";
  }
  const crosshairPlugin = {
    id: "positionCrosshair",
    afterDatasetsDraw(chartInstance) {
      const active = chartInstance.tooltip && chartInstance.tooltip.getActiveElements ? chartInstance.tooltip.getActiveElements() : [];
      const area = chartInstance.chartArea;
      if (!area || !active.length) return;
      const x = active[0].element.x;
      const c = chartInstance.ctx;
      c.save();
      c.beginPath();
      c.moveTo(x, area.top);
      c.lineTo(x, area.bottom);
      c.lineWidth = 1;
      c.strokeStyle = "rgba(255,255,255,0.22)";
      c.stroke();
      c.restore();
    },
  };

  // ---------------------------------------------------------------------
  // Modal DOM (built once, on demand) + open/close
  // ---------------------------------------------------------------------
  function ensureModal() {
    if (document.getElementById("position-modal-backdrop")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="position-modal-backdrop" id="position-modal-backdrop" hidden>
        <div class="position-modal" id="position-modal" role="dialog" aria-modal="true" aria-labelledby="position-modal-title">
          <button type="button" class="position-modal-close" id="position-modal-close" aria-label="Close price chart">&times;</button>
          <div class="position-modal-head">
            <h2 class="position-modal-title" id="position-modal-title">—</h2>
            <p class="position-modal-sub" id="position-modal-sub"></p>
          </div>
          <div class="chart-canvas-wrap position-modal-canvas-wrap" id="position-modal-canvas-wrap">
            <canvas id="position-modal-canvas"></canvas>
          </div>
          <p class="empty-state position-modal-empty" id="position-modal-empty" hidden></p>
          <p class="chart-summary position-modal-summary" id="position-modal-summary"></p>
        </div>
      </div>`;
    document.body.appendChild(wrap.firstElementChild);

    document.getElementById("position-modal-close").addEventListener("click", closeModal);
    document.getElementById("position-modal-backdrop").addEventListener("click", (e) => {
      if (e.target.id === "position-modal-backdrop") closeModal();
    });
    document.addEventListener("keydown", (e) => {
      const backdrop = document.getElementById("position-modal-backdrop");
      if (!backdrop || backdrop.hidden) return;
      if (e.key === "Escape") { closeModal(); return; }
      // Minimal focus trap: this modal has exactly one focusable
      // control (the close button), so Tab/Shift+Tab just keeps focus
      // on it rather than escaping to the page underneath.
      if (e.key === "Tab") {
        e.preventDefault();
        document.getElementById("position-modal-close").focus();
      }
    });
  }

  function destroyChart() {
    if (chart) { chart.destroy(); chart = null; }
  }
  function showEmpty(message) {
    const empty = document.getElementById("position-modal-empty");
    const wrap = document.getElementById("position-modal-canvas-wrap");
    empty.hidden = false;
    empty.textContent = message;
    wrap.hidden = true;
  }

  async function openModal(symbol, triggerEl) {
    lastFocused = triggerEl || document.activeElement;
    ensureModal();
    const backdrop = document.getElementById("position-modal-backdrop");
    const titleEl = document.getElementById("position-modal-title");
    const subEl = document.getElementById("position-modal-sub");
    const emptyEl = document.getElementById("position-modal-empty");
    const wrapEl = document.getElementById("position-modal-canvas-wrap");
    const summaryEl = document.getElementById("position-modal-summary");
    const modalEl = document.getElementById("position-modal");

    titleEl.textContent = symbol;
    subEl.textContent = "Loading price history…";
    emptyEl.hidden = true;
    wrapEl.hidden = false;
    summaryEl.textContent = "";
    modalEl.classList.remove("trend-up", "trend-down");
    destroyChart();
    backdrop.hidden = false;
    document.body.classList.add("position-modal-open");
    document.getElementById("position-modal-close").focus();

    const data = historyData || (await loadHistory());

    if (!data || data.available === false) {
      subEl.textContent = "";
      showEmpty((data && data.reason) || "Live position/price data wasn't fetched for this run.");
      return;
    }
    const sym = (data.symbols || {})[symbol];
    if (!sym) {
      subEl.textContent = "";
      showEmpty("No price history recorded yet for this position.");
      return;
    }
    if (sym.available === false) {
      subEl.textContent = sym.entry_utc ? `Since ${fmtDateET(sym.entry_utc)}` : "Recent price history";
      showEmpty(sym.reason || "Price history couldn't be fetched for this symbol.");
      return;
    }
    const points = sym.points || [];
    if (points.length < 2) {
      subEl.textContent = sym.entry_utc ? `Since ${fmtDateET(sym.entry_utc)}` : "Recent price history";
      showEmpty("Not enough recorded price history yet to draw a chart.");
      return;
    }

    subEl.textContent = sym.entry_is_estimated
      ? "Recent price history (exact purchase date not clearly determined from the trade log)"
      : `Since purchase · ${fmtDateET(sym.entry_utc)}`;

    renderChart(points, symbol);
  }

  function closeModal() {
    const backdrop = document.getElementById("position-modal-backdrop");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    document.body.classList.remove("position-modal-open");
    destroyChart();
    hideTooltip();
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function renderChart(points, symbol) {
    if (typeof Chart === "undefined") {
      showEmpty("Charting library failed to load.");
      return;
    }
    currentSeries = points;
    currentEntryPrice = points[0].price;
    currentSymbolLabel = symbol;

    const first = points[0].price;
    const last = points[points.length - 1].price;
    const up = last >= first;
    const trendColor = up ? COLORS.green : COLORS.red;
    const segmentColor = (segCtx) => (segCtx.p1.parsed.y >= first ? COLORS.green : COLORS.red);

    const canvas = document.getElementById("position-modal-canvas");
    chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: points.map((_, i) => i),
        datasets: [{
          label: symbol,
          data: points.map((p) => p.price),
          borderColor: trendColor,
          backgroundColor: trendColor,
          segment: { borderColor: segmentColor },
          fill: false,
          borderWidth: 2,
          tension: 0.18,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: trendColor,
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: "#050706",
          spanGaps: false,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: REDUCED_MOTION ? false : { duration: 220 },
        interaction: { mode: "index", intersect: false, axis: "x" },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false, external: externalTooltip },
        },
        scales: {
          x: {
            ticks: {
              color: COLORS.text, maxTicksLimit: 6, autoSkip: true, maxRotation: 0, minRotation: 0, font: { size: 10 },
              callback(value) {
                const p = points[value];
                return p ? fmtAxisDate(p.t) : "";
              },
            },
            grid: { color: COLORS.grid, drawTicks: false },
            border: { display: false },
          },
          y: {
            beginAtZero: false,
            ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 6, callback: (v) => fmtPrice(v) },
            grid: { color: COLORS.grid, drawTicks: false },
            border: { display: false },
          },
        },
      },
      plugins: [crosshairPlugin],
    });

    const changePct = first ? ((last / first) - 1) * 100 : null;
    const summaryEl = document.getElementById("position-modal-summary");
    summaryEl.innerHTML = `${points.length} recorded price point${points.length === 1 ? "" : "s"}, ` +
      `${fmtPrice(first)} &rarr; ${fmtPrice(last)}` +
      (isNum(changePct) ? ` (<span class="${changePct >= 0 ? "positive" : "negative"}">${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%</span>)` : "");

    const modalEl = document.getElementById("position-modal");
    modalEl.classList.toggle("trend-up", up);
    modalEl.classList.toggle("trend-down", !up);
  }

  // ---------------------------------------------------------------------
  // Click/keyboard delegation - works on any .position-card[data-symbol]
  // anywhere in the document, however and whenever it was inserted.
  // ---------------------------------------------------------------------
  function findCard(target) {
    return target && target.closest ? target.closest("[data-symbol]") : null;
  }
  document.addEventListener("click", (e) => {
    const card = findCard(e.target);
    if (!card || !card.dataset.symbol) return;
    openModal(card.dataset.symbol, card);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = findCard(e.target);
    if (!card || card !== document.activeElement || !card.dataset.symbol) return;
    e.preventDefault();
    openModal(card.dataset.symbol, card);
  });

  document.addEventListener("DOMContentLoaded", () => {
    ensureModal();
    loadHistory();
  });
})();
