/*
 * Shared price-chart modal for both position cards (Positions tab) and
 * Ticker Tracker cards - loaded by both index.html and charts.html.
 * Listens for clicks/keypresses on any element carrying a data-symbol
 * attribute via delegation on `document`, so it works regardless of
 * whether dashboard.js or charts.js rendered the card, and regardless of
 * when (asynchronously, via innerHTML) that card was inserted - no need
 * to coordinate boot order with either page's own renderer.
 *
 * Two modes share one modal/chart implementation (same DOM, same
 * tooltip/crosshair/reference-line plugins) rather than two near-
 * duplicate copies:
 *   - Position mode (data-tracker unset): reads site/data/
 *     position_history.json, always shows the single "since purchase"
 *     span, and draws one dashed reference line at the entry price.
 *   - Tracker mode (data-tracker="true"): reads site/data/
 *     ticker_charts.json, shows a 1 Day/1 Week/1 Month/100 Day range
 *     selector (all four already fetched server-side, so switching is
 *     instant with no extra network call), and draws a dashed reference
 *     line at the ticker's current 100-day SMA - every watched ticker
 *     has one of those regardless of whether it's held - plus a second
 *     one at the real entry price when the ticker is currently held.
 *     Both lines carry their own on-canvas text label (not just a hover
 *     tooltip), and the y-axis is always widened to keep every active
 *     line actually visible rather than silently clipped off-screen.
 *
 * Both JSON files are real Alpaca historical prices this project's own
 * site_data.py already fetched server-side, never fabricated here. A
 * symbol/range with no data yet (feature not enabled for this run, a
 * per-symbol fetch failure, too few points) shows an honest message
 * instead of a chart - see the state handling in openModal()/
 * openTrackerModal().
 */

(function () {
  "use strict";

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // avgLine/entryLine are the two reference-line colors - distinct from
  // green/red (which mean "price up/down") and from each other, so a
  // tracker chart showing both an SMA line and an entry-price line at
  // once never leaves it ambiguous which is which even without hovering.
  const COLORS = { green: "#34d372", red: "#f0554a", text: "#9aa5a0", grid: "rgba(255,255,255,0.06)", avgLine: "#6aa6ff", entryLine: "#f0a63c" };

  // Chart.js's own default font is a generic sans-serif that doesn't
  // match the rest of the page (Inter) - set once, globally, here since
  // this file loads right after the Chart.js CDN script on both pages,
  // before any chart (this project's own or charts.js's) is built.
  if (typeof Chart !== "undefined") {
    Chart.defaults.font.family = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    Chart.defaults.color = COLORS.text;
  }

  let historyData = null;
  let historyPromise = null;
  let tickerChartsData = null;
  let tickerChartsPromise = null;
  let chart = null;
  let lastFocused = null;
  // Zero, one, or two dashed reference lines on the current chart - each
  // {value, label, color, dash}. Position mode always has exactly one
  // (entry price); tracker mode has the 100-day SMA plus, only when the
  // ticker is currently held, a second one at its real entry price.
  let currentReferenceLines = [];
  let currentSymbolLabel = "";
  let currentSeries = [];
  // Tracker-mode-only state - all null/unset in position mode.
  let currentMode = "position";
  let currentRangeKey = null;
  let currentTickerRanges = null;
  let currentTrackerTicker = "";

  const RANGE_ORDER = ["1d", "1w", "1m", "100d"];
  const RANGE_LABELS = { "1d": "1 Day", "1w": "1 Week", "1m": "1 Month", "100d": "100 Day" };
  const RANGE_BTN_LABELS = { "1d": "1D", "1w": "1W", "1m": "1M", "100d": "100D" };
  const INTERVAL_LABELS = { "5m": "5-minute bars", "15m": "15-minute bars", "1h": "hourly bars", "1d": "daily bars" };

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
  function loadTickerCharts() {
    if (tickerChartsPromise) return tickerChartsPromise;
    tickerChartsPromise = fetch("data/ticker_charts.json", { cache: "no-store" })
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
        tickerChartsData = data;
        return data;
      });
    return tickerChartsPromise;
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
  function fmtAxisTime(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true }).format(d);
  }
  // 1-day range gets intraday time labels (a date label would repeat
  // the same day across nearly every tick) - every other range keeps
  // the plain month/day label, same as position mode always used.
  function fmtAxisLabel(iso, rangeKey) {
    return rangeKey === "1d" ? fmtAxisTime(iso) : fmtAxisDate(iso);
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
    // Signed color for the overall tooltip border - the first reference
    // line (position mode's only one, or tracker mode's 100-day avg)
    // still drives that, same as before this supported more than one.
    const primaryPct = currentReferenceLines.length && isNum(currentReferenceLines[0].value)
      ? ((point.price / currentReferenceLines[0].value) - 1) * 100
      : null;

    let html = `<div class="tt-title">${currentSymbolLabel}</div>`;
    html += `<div class="tt-time">${fmtDateTimeET(point.t)}</div>`;
    html += `<div class="tt-rows">`;
    html += `<div class="tt-row"><span class="tt-label">Price</span><span class="tt-val">${fmtPrice(point.price)}</span></div>`;
    currentReferenceLines.forEach((line) => {
      if (!isNum(line.value)) return;
      const pct = ((point.price / line.value) - 1) * 100;
      html += `<div class="tt-row"><span class="tt-label">${line.label}</span><span class="tt-val ${pct >= 0 ? "positive" : "negative"}">${(pct >= 0 ? "+" : "") + pct.toFixed(2)}%</span></div>`;
    });
    html += `</div>`;
    el.innerHTML = html;
    el.style.borderColor = isNum(primaryPct) ? (primaryPct >= 0 ? COLORS.green : COLORS.red) : "";
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

  // Dashed reference line(s) at whichever value(s) this chart's framing
  // is measured against - the entry price in position mode, or the
  // ticker's 100-day SMA (plus a second line at the real entry price if
  // currently held) in tracker mode. Each line draws its own text label
  // directly on the canvas (not just a hover tooltip) so what it means
  // is never a mystery, and the y-axis scale (see renderChart) is
  // always widened to guarantee every line is actually visible, not
  // silently clipped off when a range's own price swing sits far from it.
  const referenceLinePlugin = {
    id: "chartReferenceLines",
    beforeDatasetsDraw(chartInstance) {
      const yScale = chartInstance.scales.y;
      const area = chartInstance.chartArea;
      if (!yScale || !area || !currentReferenceLines.length) return;
      const c = chartInstance.ctx;
      currentReferenceLines.forEach((line, i) => {
        if (!isNum(line.value)) return;
        const py = yScale.getPixelForValue(line.value);
        if (py < area.top - 1 || py > area.bottom + 1) return;
        c.save();
        c.beginPath();
        c.setLineDash(line.dash || [4, 4]);
        c.moveTo(area.left, py);
        c.lineTo(area.right, py);
        c.lineWidth = 1;
        c.strokeStyle = line.color;
        c.stroke();
        c.restore();

        // Alternate label placement above/below the line so two close-
        // together lines (e.g. SMA and entry price near each other)
        // don't draw their text on top of one another.
        c.save();
        c.font = "600 10px 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
        c.fillStyle = line.color;
        c.textAlign = "right";
        const labelY = i % 2 === 0 ? Math.max(py - 6, area.top + 10) : Math.min(py + 14, area.bottom - 4);
        c.fillText(line.label, area.right - 6, labelY);
        c.restore();
      });
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
          <div class="segmented position-modal-ranges" id="position-modal-ranges" role="group" aria-label="Chart range" hidden>
            ${RANGE_ORDER.map((key) => `<button type="button" data-range-key="${key}">${RANGE_BTN_LABELS[key]}</button>`).join("")}
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
    document.getElementById("position-modal-ranges").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-range-key]");
      if (btn) selectRange(btn.dataset.rangeKey);
    });
    document.addEventListener("keydown", (e) => {
      const backdrop = document.getElementById("position-modal-backdrop");
      if (!backdrop || backdrop.hidden) return;
      if (e.key === "Escape") { closeModal(); return; }
      // Minimal focus trap: this modal's only focusable controls are the
      // close button and (in tracker mode) the range buttons - Tab/
      // Shift+Tab cycles among whichever of those are currently visible
      // rather than escaping to the page underneath.
      if (e.key === "Tab") {
        e.preventDefault();
        const focusable = [document.getElementById("position-modal-close")];
        if (currentMode === "tracker") {
          focusable.push(...document.querySelectorAll("#position-modal-ranges button"));
        }
        const idx = focusable.indexOf(document.activeElement);
        const next = e.shiftKey
          ? focusable[(idx <= 0 ? focusable.length : idx) - 1]
          : focusable[(idx + 1) % focusable.length];
        (next || focusable[0]).focus();
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

  // Shared setup for both openModal (position) and openTrackerModal:
  // resets the modal chrome to its "loading" state and shows the
  // backdrop, before either mode's own data-specific logic takes over.
  function openModalShell(symbol, triggerEl, loadingText) {
    lastFocused = triggerEl || document.activeElement;
    ensureModal();
    const backdrop = document.getElementById("position-modal-backdrop");
    const titleEl = document.getElementById("position-modal-title");
    const subEl = document.getElementById("position-modal-sub");
    const emptyEl = document.getElementById("position-modal-empty");
    const wrapEl = document.getElementById("position-modal-canvas-wrap");
    const summaryEl = document.getElementById("position-modal-summary");
    const modalEl = document.getElementById("position-modal");
    const rangesEl = document.getElementById("position-modal-ranges");

    titleEl.textContent = symbol;
    subEl.textContent = loadingText;
    emptyEl.hidden = true;
    wrapEl.hidden = false;
    summaryEl.textContent = "";
    modalEl.classList.remove("trend-up", "trend-down");
    rangesEl.hidden = true;
    rangesEl.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    destroyChart();
    backdrop.hidden = false;
    document.body.classList.add("position-modal-open");
    document.getElementById("position-modal-close").focus();
  }

  async function openModal(symbol, triggerEl) {
    currentMode = "position";
    currentRangeKey = null;
    currentTickerRanges = null;
    openModalShell(symbol, triggerEl, "Loading price history…");
    const subEl = document.getElementById("position-modal-sub");

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

    renderChart(points, symbol, [{ value: points[0].price, label: "Entry", color: COLORS.entryLine, dash: [4, 4] }]);
  }

  async function openTrackerModal(ticker, triggerEl) {
    currentMode = "tracker";
    currentTrackerTicker = ticker;
    openModalShell(ticker, triggerEl, "Loading price history…");
    const rangesEl = document.getElementById("position-modal-ranges");
    rangesEl.hidden = false;

    const data = tickerChartsData || (await loadTickerCharts());

    if (!data || data.available === false) {
      const subEl = document.getElementById("position-modal-sub");
      subEl.textContent = "";
      rangesEl.hidden = true;
      showEmpty((data && data.reason) || "Live ticker chart data wasn't fetched for this run.");
      return;
    }
    const sym = (data.symbols || {})[ticker];
    if (!sym || sym.available === false) {
      const subEl = document.getElementById("position-modal-sub");
      subEl.textContent = "";
      rangesEl.hidden = true;
      showEmpty((sym && sym.reason) || "No chart data recorded yet for this ticker.");
      return;
    }

    currentTickerRanges = sym;
    // "100d" is the default view - see position-chart.js's module
    // docstring for why: the 100-day range is what the Ticker Tracker
    // card itself already summarizes as text, so opening on it keeps
    // the chart's first view consistent with what was just clicked.
    selectRange("100d");
  }

  function selectRange(rangeKey) {
    if (!currentTickerRanges) return;
    currentRangeKey = rangeKey;
    document.querySelectorAll("#position-modal-ranges button").forEach((b) => {
      b.classList.toggle("active", b.dataset.rangeKey === rangeKey);
    });

    const range = currentTickerRanges.ranges[rangeKey];
    const subEl = document.getElementById("position-modal-sub");
    const intervalLabel = range && range.interval ? INTERVAL_LABELS[range.interval] || range.interval : "";
    subEl.textContent = intervalLabel ? `${RANGE_LABELS[rangeKey]} · ${intervalLabel}` : RANGE_LABELS[rangeKey];

    if (!range || range.available === false || !range.points || range.points.length < 2) {
      destroyChart();
      showEmpty((range && range.reason) || "Not enough recorded price history yet for this range.");
      return;
    }
    document.getElementById("position-modal-empty").hidden = true;
    document.getElementById("position-modal-canvas-wrap").hidden = false;

    const referenceLines = [];
    if (isNum(currentTickerRanges.sma100)) {
      referenceLines.push({ value: currentTickerRanges.sma100, label: "100-Day Avg", color: COLORS.avgLine, dash: [4, 4] });
    }
    // Only currently-held tickers have a real entry price - see
    // site_data.py's build_ticker_charts.
    if (currentTickerRanges.held && isNum(currentTickerRanges.entry_price)) {
      referenceLines.push({ value: currentTickerRanges.entry_price, label: "Entry", color: COLORS.entryLine, dash: [2, 3] });
    }
    renderChart(range.points, currentTrackerTicker, referenceLines);
  }

  function closeModal() {
    const backdrop = document.getElementById("position-modal-backdrop");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    document.body.classList.remove("position-modal-open");
    destroyChart();
    hideTooltip();
    currentMode = "position";
    currentRangeKey = null;
    currentTickerRanges = null;
    currentTrackerTicker = "";
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function renderChart(points, symbol, referenceLines) {
    if (typeof Chart === "undefined") {
      showEmpty("Charting library failed to load.");
      return;
    }
    // Tracker mode can call this more than once per modal session (each
    // range switch re-renders) - always tear down the previous Chart.js
    // instance first, the same way openModalShell already does for the
    // very first render, or Chart.js would either throw ("Canvas is
    // already in use") or silently leave the old chart's data on screen.
    destroyChart();
    currentSeries = points;
    currentReferenceLines = Array.isArray(referenceLines) ? referenceLines.filter((l) => isNum(l.value)) : [];
    currentSymbolLabel = symbol;

    const first = points[0].price;
    const last = points[points.length - 1].price;
    const up = last >= first;
    const trendColor = up ? COLORS.green : COLORS.red;
    const segmentColor = (segCtx) => (segCtx.p1.parsed.y >= first ? COLORS.green : COLORS.red);

    // Widen the y-axis to guarantee every reference line actually lands
    // inside the chart area, rather than being silently clipped off
    // whenever a range's own price swing sits far from it (e.g. a 1-day
    // view next to a 100-day average from weeks ago) - see this file's
    // module docstring and referenceLinePlugin above.
    const prices = points.map((p) => p.price);
    let yMin = Math.min(...prices);
    let yMax = Math.max(...prices);
    currentReferenceLines.forEach((line) => {
      yMin = Math.min(yMin, line.value);
      yMax = Math.max(yMax, line.value);
    });
    const yPad = (yMax - yMin) * 0.08 || Math.abs(yMax) * 0.02 || 1;
    yMin -= yPad;
    yMax += yPad;

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
                return p ? fmtAxisLabel(p.t, currentRangeKey) : "";
              },
            },
            grid: { color: COLORS.grid, drawTicks: false },
            border: { display: false },
          },
          y: {
            beginAtZero: false,
            min: yMin,
            max: yMax,
            ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 6, callback: (v) => fmtPrice(v) },
            grid: { color: COLORS.grid, drawTicks: false },
            border: { display: false },
          },
        },
      },
      plugins: [crosshairPlugin, referenceLinePlugin],
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
  // Click/keyboard delegation - works on any [data-symbol] card anywhere
  // in the document, however and whenever it was inserted. data-tracker
  // distinguishes a Ticker Tracker card (range-selectable chart) from a
  // position card (single "since purchase" span).
  // ---------------------------------------------------------------------
  function findCard(target) {
    return target && target.closest ? target.closest("[data-symbol]") : null;
  }
  function openCard(card) {
    if (card.dataset.tracker === "true") {
      openTrackerModal(card.dataset.symbol, card);
    } else {
      openModal(card.dataset.symbol, card);
    }
  }
  document.addEventListener("click", (e) => {
    const card = findCard(e.target);
    if (!card || !card.dataset.symbol) return;
    openCard(card);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = findCard(e.target);
    if (!card || card !== document.activeElement || !card.dataset.symbol) return;
    e.preventDefault();
    openCard(card);
  });

  document.addEventListener("DOMContentLoaded", () => {
    ensureModal();
    loadHistory();
  });
})();
