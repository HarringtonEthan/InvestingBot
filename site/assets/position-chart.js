/*
 * Shared price-chart modal - loaded by both index.html and charts.html,
 * opened by clicking ANY card carrying a data-symbol attribute: a
 * position card (Positions tab, or charts.html's own Positions panels)
 * or a Ticker Tracker card. Listens via delegation on `document`, so it
 * works regardless of whether dashboard.js or charts.js rendered the
 * card, and regardless of when (asynchronously, via innerHTML) that
 * card was inserted - no need to coordinate boot order with either
 * page's own renderer.
 *
 * Deliberately ONE mode, not two: every card - held or not, wherever it
 * lives on the site - opens the exact same range-selectable (1 Day/
 * 1 Week/1 Month/100 Day) chart, reading the exact same file
 * (site/data/ticker_charts.json, keyed by the bare ticker). An earlier
 * version of this file had a second "position mode" (a fixed "since
 * purchase" span, no range selector) for position cards specifically -
 * removed because it meant the exact same ticker showed a different
 * click-to-chart experience depending on which tab you found it in,
 * and because its "entry" reference line was approximated from the
 * first fetched history bar instead of the position's real average
 * entry price, which could disagree with the position card's own P&L
 * sign right next to it. ticker_charts.json already covers every
 * watched ticker, held or not, with the real entry price and exact
 * entry timestamp when one is held - there was nothing position mode
 * did that this can't do strictly more accurately.
 *
 * Every ticker gets a dashed "100-Day Avg" reference line (the same
 * number the Ticker Tracker card's own text already shows). A
 * currently-held ticker also gets a second dashed "Entry" line at its
 * real Alpaca average entry price - drawn starting only from the exact
 * timestamp that position was actually opened (see entry_utc), not
 * across the whole visible chart, so it never implies the position was
 * held longer than it actually was. The lines themselves are deliberately
 * bare on the canvas - no on-canvas text - a persistent legend below
 * the range buttons (see buildLegend) is what explains what each one
 * means and its current value, since crowding the chart itself with
 * text made it harder to read, not easier. The y-axis is always
 * widened to keep every active line actually visible rather than
 * silently clipped off-screen.
 *
 * The price line itself, and the modal's own trend accent, are colored
 * relative to whichever reference line is most meaningful for this
 * ticker - the real entry price if held, otherwise the 100-day average
 * - rather than simply "up or down since the left edge of whatever
 * range happens to be selected." For a HELD ticker specifically, the
 * modal's own top-level up/down read (border accent, legend %, fill
 * color) always comes from the position's real live unrealized P&L
 * (ticker_charts.json's live_unrealized_plpc - the exact number the
 * card itself is colored by), never from comparing entry price against
 * whatever historical bar happens to be the last point in the
 * currently-selected range. Those two used to disagree in a genuinely
 * confusing way: the default view is 100 Day (daily bars), whose last
 * point is *yesterday's* close - a card showing green off a live quote
 * could open a modal reading red purely because price moved since that
 * bar closed, with nothing actually wrong. Per-point segment coloring
 * along the line itself still compares each historical bar to entry
 * price (a different, legitimate "was I above or below entry back
 * then" signal) - only the one overall verdict is now always live.
 *
 * All chart data is real Alpaca historical prices this project's own
 * site_data.py already fetched server-side, never fabricated here. A
 * ticker/range with no data yet (feature not enabled for this run, a
 * per-ticker/per-range fetch failure, too few points) shows an honest
 * message instead of a chart - see the state handling in openModal().
 */

(function () {
  "use strict";

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // avgLine/entryLine are the two reference-line colors - distinct from
  // green/red (which mean "price up/down relative to the baseline") and
  // from each other, so a chart showing both an SMA line and an entry-
  // price line at once never leaves it ambiguous which is which even
  // without hovering.
  const COLORS = { green: "#34d372", red: "#f0554a", text: "#9aa5a0", grid: "rgba(255,255,255,0.06)", avgLine: "#6aa6ff", entryLine: "#f0a63c" };

  // Chart.js's own default font is a generic sans-serif that doesn't
  // match the rest of the page (Inter) - set once, globally, here since
  // this file loads right after the Chart.js CDN script on both pages,
  // before any chart (this project's own or charts.js's) is built.
  if (typeof Chart !== "undefined") {
    Chart.defaults.font.family = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    Chart.defaults.color = COLORS.text;
  }

  let chartsData = null;
  let chartsPromise = null;
  let chart = null;
  let lastFocused = null;
  // Zero, one, or two dashed reference lines on the current chart - each
  // {value, label, color, dash, kind, startAt}. Every ticker gets a
  // "100-Day Avg" line (kind: "avg"); a currently-held ticker also gets
  // an "Entry" line (kind: "entry") clipped to start at startAt (its
  // real entry timestamp) when that's known.
  let currentReferenceLines = [];
  let currentSymbolLabel = "";
  let currentSeries = [];
  let currentRangeKey = null;
  let currentTickerRanges = null;
  let currentTicker = "";
  // True only for the very first chart drawn after opening the modal -
  // that one gets a slightly longer, eased-in draw so the line visibly
  // sweeps in rather than just appearing. Every subsequent render in the
  // same modal session (switching ranges) resets this to false first,
  // so range-switching itself always stays snappy - the whole point of
  // "subtle," per this file's own module docstring, is never making the
  // user wait on an animation to see the data they just asked for.
  let isFirstRenderThisOpen = true;

  const RANGE_ORDER = ["1d", "1w", "1m", "100d"];
  const RANGE_LABELS = { "1d": "1 Day", "1w": "1 Week", "1m": "1 Month", "100d": "100 Day" };
  const RANGE_BTN_LABELS = { "1d": "1D", "1w": "1W", "1m": "1M", "100d": "100D" };
  const INTERVAL_LABELS = { "5m": "5-minute bars", "15m": "15-minute bars", "1h": "hourly bars", "1d": "daily bars" };

  // ---------------------------------------------------------------------
  // Data loading - independent of dashboard.js/charts.js's own fetches,
  // keeps this feature fully decoupled from either page's renderer.
  // ---------------------------------------------------------------------
  function loadCharts() {
    if (chartsPromise) return chartsPromise;
    chartsPromise = fetch("data/ticker_charts.json", { cache: "no-store" })
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
        chartsData = data;
        return data;
      });
    return chartsPromise;
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
  // the plain month/day label.
  function fmtAxisLabel(iso, rangeKey) {
    return rangeKey === "1d" ? fmtAxisTime(iso) : fmtAxisDate(iso);
  }

  // ---------------------------------------------------------------------
  // Custom tooltip + crosshair - reuses the exact #chart-tooltip element
  // and CSS classes charts.html's own charts already use (created here
  // if the current page doesn't already declare one, e.g. index.html),
  // so a card's price chart looks and behaves like the account
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
  function primaryReferenceLine() {
    // The one line a held/not-held ticker's own P&L or trend text is
    // actually measured against - the real entry price if held (so this
    // chart can never disagree with the card sitting right next to it),
    // otherwise the 100-day average. Everything that needs a single
    // "up or down vs. what" answer (line color, modal trend accent,
    // tooltip border) reads from this same line.
    return currentReferenceLines.find((l) => l.kind === "entry") || currentReferenceLines.find((l) => l.kind === "avg") || null;
  }
  function externalTooltip(ctx) {
    const el = tooltipEl();
    const model = ctx.tooltip;
    if (!model || model.opacity === 0) { hideTooltip(); return; }
    const idx = model.dataPoints && model.dataPoints.length ? model.dataPoints[0].dataIndex : null;
    if (idx === null || idx === undefined) return;
    const point = currentSeries[idx];
    if (!point) return;
    const primary = primaryReferenceLine();
    const primaryPct = primary && isNum(primary.value) ? ((point.price / primary.value) - 1) * 100 : null;

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

  // Dashed reference line(s) - the ticker's 100-day SMA always, plus its
  // real entry price when currently held. The entry line only draws
  // from line.startIndex onward (its real entry timestamp mapped to a
  // point index - see renderChart) rather than across the whole chart,
  // so it never implies the position was held longer than it actually
  // was; a small dot marks that exact starting point. What each line
  // means lives in the legend below the range buttons (see buildLegend),
  // not as text crowding the canvas itself - keeping the chart to just
  // the lines themselves is a lot easier to actually read. The y-axis
  // (see renderChart) is always widened to guarantee every line is
  // actually visible.
  const referenceLinePlugin = {
    id: "chartReferenceLines",
    beforeDatasetsDraw(chartInstance) {
      const yScale = chartInstance.scales.y;
      const xScale = chartInstance.scales.x;
      const area = chartInstance.chartArea;
      if (!yScale || !xScale || !area || !currentReferenceLines.length) return;
      const c = chartInstance.ctx;
      currentReferenceLines.forEach((line) => {
        if (!isNum(line.value)) return;
        const py = yScale.getPixelForValue(line.value);
        if (py < area.top - 1 || py > area.bottom + 1) return;
        let xStart = area.left;
        const clipped = isNum(line.startIndex) && line.startIndex > 0;
        if (clipped) {
          xStart = Math.min(Math.max(xScale.getPixelForValue(line.startIndex), area.left), area.right);
        }

        c.save();
        c.beginPath();
        c.setLineDash(line.dash || [4, 4]);
        c.moveTo(xStart, py);
        c.lineTo(area.right, py);
        c.lineWidth = 1.5;
        c.strokeStyle = line.color;
        c.stroke();
        c.restore();

        if (clipped) {
          // Marks exactly where the entry line begins - the real moment
          // the position was opened, not the edge of the chart.
          c.save();
          c.beginPath();
          c.arc(xStart, py, 3, 0, Math.PI * 2);
          c.fillStyle = line.color;
          c.fill();
          c.restore();
        }
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
            <p class="position-modal-meta" id="position-modal-meta" hidden></p>
          </div>
          <div class="segmented position-modal-ranges" id="position-modal-ranges" role="group" aria-label="Chart range" hidden>
            ${RANGE_ORDER.map((key) => `<button type="button" data-range-key="${key}">${RANGE_BTN_LABELS[key]}</button>`).join("")}
          </div>
          <div class="position-modal-legend" id="position-modal-legend" hidden></div>
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
      // close button and (whenever chart data loaded successfully) the
      // range buttons - Tab/Shift+Tab cycles among whichever of those
      // are currently visible rather than escaping to the page underneath.
      if (e.key === "Tab") {
        e.preventDefault();
        const rangesEl = document.getElementById("position-modal-ranges");
        const focusable = [document.getElementById("position-modal-close")];
        if (rangesEl && !rangesEl.hidden) {
          focusable.push(...rangesEl.querySelectorAll("button"));
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
    const legend = document.getElementById("position-modal-legend");
    empty.hidden = false;
    empty.textContent = message;
    wrap.hidden = true;
    legend.hidden = true;
  }

  function heldMetaText(sym) {
    if (!sym.held) return null;
    if (sym.entry_utc && !sym.entry_is_estimated) {
      return `Bought ${fmtPrice(sym.entry_price)} on ${fmtDateET(sym.entry_utc)}`;
    }
    return `Bought ${fmtPrice(sym.entry_price)} (exact purchase date not clearly determined from the trade log)`;
  }

  async function openModal(ticker, triggerEl) {
    currentTicker = ticker;
    currentRangeKey = null;
    currentTickerRanges = null;
    isFirstRenderThisOpen = true;
    lastFocused = triggerEl || document.activeElement;
    ensureModal();
    const backdrop = document.getElementById("position-modal-backdrop");
    const titleEl = document.getElementById("position-modal-title");
    const subEl = document.getElementById("position-modal-sub");
    const metaEl = document.getElementById("position-modal-meta");
    const emptyEl = document.getElementById("position-modal-empty");
    const wrapEl = document.getElementById("position-modal-canvas-wrap");
    const legendEl = document.getElementById("position-modal-legend");
    const summaryEl = document.getElementById("position-modal-summary");
    const modalEl = document.getElementById("position-modal");
    const rangesEl = document.getElementById("position-modal-ranges");

    titleEl.textContent = ticker;
    subEl.textContent = "Loading price history…";
    metaEl.hidden = true;
    emptyEl.hidden = true;
    wrapEl.hidden = false;
    legendEl.hidden = true;
    summaryEl.textContent = "";
    modalEl.classList.remove("trend-up", "trend-down");
    rangesEl.hidden = true;
    rangesEl.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    destroyChart();
    backdrop.hidden = false;
    document.body.classList.add("position-modal-open");
    document.getElementById("position-modal-close").focus();

    const data = chartsData || (await loadCharts());

    if (!data || data.available === false) {
      subEl.textContent = "";
      showEmpty((data && data.reason) || "Live ticker chart data wasn't fetched for this run.");
      return;
    }
    const sym = (data.symbols || {})[ticker];
    if (!sym || sym.available === false) {
      subEl.textContent = "";
      showEmpty((sym && sym.reason) || "No chart data recorded yet for this ticker.");
      return;
    }

    currentTickerRanges = sym;
    const metaText = heldMetaText(sym);
    if (metaText) {
      metaEl.hidden = false;
      metaEl.innerHTML = `<span class="position-modal-held-badge">Held</span> ${metaText}`;
    }
    rangesEl.hidden = false;
    // "100d" is the default view for every card, held or not - the
    // same range every card's own summary text is already measured
    // against, so opening the modal never disagrees with what was just
    // clicked, and every card gives the same first impression.
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
      referenceLines.push({ value: currentTickerRanges.sma100, label: "100-Day Avg", color: COLORS.avgLine, dash: [4, 4], kind: "avg" });
    }
    // Only currently-held tickers have a real entry price - see
    // site_data.py's build_ticker_charts. startAt (the position's exact
    // entry timestamp) is only set when the trade log clearly supports
    // one - otherwise the line falls back to spanning the whole chart
    // rather than guessing where it should start.
    if (currentTickerRanges.held && isNum(currentTickerRanges.entry_price)) {
      referenceLines.push({
        value: currentTickerRanges.entry_price,
        label: "Entry",
        color: COLORS.entryLine,
        dash: [2, 3],
        kind: "entry",
        startAt: currentTickerRanges.entry_is_estimated ? null : currentTickerRanges.entry_utc,
      });
    }
    renderChart(range.points, currentTicker, referenceLines);
  }

  function closeModal() {
    const backdrop = document.getElementById("position-modal-backdrop");
    if (!backdrop || backdrop.hidden) return;
    backdrop.hidden = true;
    document.body.classList.remove("position-modal-open");
    destroyChart();
    hideTooltip();
    currentRangeKey = null;
    currentTickerRanges = null;
    currentTicker = "";
    if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
  }

  function buildLegend(referenceLines, lastPrice) {
    const el = document.getElementById("position-modal-legend");
    if (!referenceLines.length) { el.hidden = true; el.innerHTML = ""; return; }
    el.hidden = false;
    el.innerHTML = referenceLines.map((line) => {
      // The Entry chip's % always comes from the position's real live
      // unrealized_plpc when it's known (same number the card itself
      // shows) rather than being recomputed from lastPrice - lastPrice
      // is only the last point of whichever historical range happens
      // to be on screen, which can lag the live quote by anywhere from
      // minutes (1D) to a full trading day (100D's daily bars).
      const livePct = line.kind === "entry" && currentTickerRanges && isNum(currentTickerRanges.live_unrealized_plpc)
        ? currentTickerRanges.live_unrealized_plpc * 100
        : null;
      const pct = isNum(livePct) ? livePct : (isNum(line.value) && line.value ? ((lastPrice / line.value) - 1) * 100 : null);
      const pctHtml = isNum(pct) ? ` <span class="modal-legend-pct ${pct >= 0 ? "positive" : "negative"}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span>` : "";
      // A small pulsing dot marks the one number on this chart that's
      // truly live (vs. every other figure here, which is only as
      // fresh as the currently-selected range's own last bar) - the
      // same visual language the page's own "Last updated" indicator
      // already uses, so "live" reads consistently sitewide.
      const liveTag = isNum(livePct) ? ` <span class="modal-legend-live"><span class="live-dot"></span>live</span>` : "";
      return `<span class="modal-legend-chip"><span class="modal-legend-swatch" style="background:${line.color}"></span>${line.label}: ${fmtPrice(line.value)}${pctHtml}${liveTag}</span>`;
    }).join("");
  }

  function renderChart(points, symbol, referenceLines) {
    if (typeof Chart === "undefined") {
      showEmpty("Charting library failed to load.");
      return;
    }
    // A range switch re-renders on the same modal instance - always
    // tear down the previous Chart.js instance first, or Chart.js would
    // either throw ("Canvas is already in use") or silently leave the
    // old chart's data on screen.
    destroyChart();
    currentSeries = points;
    currentSymbolLabel = symbol;
    currentReferenceLines = Array.isArray(referenceLines) ? referenceLines.filter((l) => isNum(l.value)) : [];

    // Maps each reference line's real-world startAt timestamp to a
    // point index in *this* range's series, so referenceLinePlugin can
    // clip the entry line to start exactly there instead of at the left
    // edge. No startAt (unknown/estimated entry) or an entry that
    // predates every point in view both mean "draw across the whole
    // chart" - startIndex stays null.
    currentReferenceLines.forEach((line) => {
      if (!line.startAt) { line.startIndex = null; return; }
      const startMs = new Date(line.startAt).getTime();
      const idx = points.findIndex((p) => new Date(p.t).getTime() >= startMs);
      line.startIndex = idx > 0 ? idx : null;
    });

    const last = points[points.length - 1].price;
    // Per-point segment coloring still compares each historical bar
    // against the primary reference line (real entry price if held,
    // else the 100-day average) - a legitimate "was I above or below
    // this back then" signal. baseline drives that; it is NOT what
    // decides the chart's one overall verdict below.
    const primary = primaryReferenceLine();
    const baseline = primary ? primary.value : points[0].price;
    // The ONE overall up/down verdict (modal border accent, fill
    // color, point-hover default) comes from the position's real live
    // unrealized_plpc when held - the exact number the card that was
    // just clicked is itself colored by - never from comparing entry
    // price to whatever historical bar happens to be the last point of
    // the currently-selected range. Those can disagree in a genuinely
    // confusing way: the default view is 100 Day (daily bars), whose
    // last point is *yesterday's* close, so a card reading green off a
    // live quote could open a modal reading red purely because price
    // moved since that bar closed - nothing actually wrong, just two
    // different points in time being compared. A not-held ticker has
    // no live P&L to read, so it still falls back to baseline.
    const liveUp = currentTickerRanges && currentTickerRanges.held && isNum(currentTickerRanges.live_unrealized_plpc)
      ? currentTickerRanges.live_unrealized_plpc >= 0
      : null;
    const up = liveUp !== null ? liveUp : last >= baseline;
    const trendColor = up ? COLORS.green : COLORS.red;
    const segmentColor = (segCtx) => (segCtx.p1.parsed.y >= baseline ? COLORS.green : COLORS.red);

    // Widen the y-axis to guarantee every reference line actually lands
    // inside the chart area, rather than being silently clipped off
    // whenever a range's own price swing sits far from it (e.g. a 1-day
    // view next to a 100-day average from weeks ago).
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
          backgroundColor(context) {
            // A soft gradient fill under the line, top-to-transparent -
            // needs the chart's own layout, which isn't available until
            // after the first pass, so this scriptable callback (Chart.js
            // re-invokes it every render) falls back to a flat color
            // until chartArea exists.
            const { ctx: c, chartArea: area } = context.chart;
            if (!area) return trendColor;
            const gradient = c.createLinearGradient(0, area.top, 0, area.bottom);
            gradient.addColorStop(0, trendColor + "2e");
            gradient.addColorStop(1, trendColor + "00");
            return gradient;
          },
          segment: { borderColor: segmentColor },
          fill: true,
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
        // The very first chart drawn after opening the modal eases its
        // line in a bit more noticeably (longer duration, an easing
        // curve) - every later render in the same session (switching
        // ranges) drops straight back to a quick, near-instant redraw,
        // so flipping between 1D/1W/1M/100D never feels like it's
        // making anyone wait on an animation.
        animation: REDUCED_MOTION ? false : (isFirstRenderThisOpen ? { duration: 420, easing: "easeOutQuart" } : { duration: 150 }),
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
    isFirstRenderThisOpen = false;

    buildLegend(currentReferenceLines, last);

    const first = points[0].price;
    const changePct = first ? ((last / first) - 1) * 100 : null;
    const summaryEl = document.getElementById("position-modal-summary");
    summaryEl.innerHTML = `${points.length} recorded price point${points.length === 1 ? "" : "s"} in this window, ` +
      `${fmtPrice(first)} &rarr; ${fmtPrice(last)}` +
      (isNum(changePct) ? ` (<span class="${changePct >= 0 ? "positive" : "negative"}">${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%</span>)` : "");

    const modalEl = document.getElementById("position-modal");
    modalEl.classList.toggle("trend-up", up);
    modalEl.classList.toggle("trend-down", !up);
  }

  // ---------------------------------------------------------------------
  // Click/keyboard delegation - works on any [data-symbol] card anywhere
  // in the document, however and whenever it was inserted. Every card
  // opens the exact same modal - see this file's module docstring for
  // why there's no longer a second "position mode."
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
    loadCharts();
  });
})();
