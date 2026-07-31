/*
 * InvestingBot - interactive charts page (charts.html).
 *
 * Mirrors visualize_log.py's PNG dashboard panel-for-panel, on request,
 * so the two never look like they're showing different things: net
 * account gain/loss (whole account), then crypto and stocks each get
 * their own cumulative-realized-P&L chart, win/loss-per-ticker chart,
 * and open-positions cards - never blended into one combined view,
 * same reasoning visualize_log.py's own docstring gives (a mean-
 * reversion crypto strategy and a day-trading stock strategy don't
 * belong on the same line).
 *
 * ACCURACY RULES enforced throughout (see also site_data.py):
 *  - A tooltip's timestamp and its values always come from the same
 *    underlying record. A series with no sample at a given timestamp
 *    renders as a real gap and its tooltip reads "No recorded value" -
 *    never zero-filled, never interpolated.
 *  - Realized P&L only ever comes from confirmed-fill SELL rows, the
 *    same definition site_data.py uses server-side.
 *  - Range boundaries (Today/This Week/This Month) are read directly
 *    from dashboard.json's own periods, which already include
 *    site_data.py's reset/relaunch baseline anchoring - this page can
 *    never disagree with the main dashboard's numbers because it's
 *    reading the exact same computed boundaries and baseline, not
 *    recomputing its own.
 */

(function () {
  "use strict";

  // Runs synchronously the moment this file parses - only reason
  // .chart-section-group's opacity:0 starting state in styles.css is
  // scoped behind this class, so if this script 404s or fails to parse
  // for any reason, every section just renders visible immediately
  // (the safe default) instead of silently staying hidden forever.
  document.body.classList.add("reveal-ready");

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const IS_TOUCH = window.matchMedia("(hover: none)").matches;

  let dashboard = null;
  let trades = null;
  let equity = null;
  let positions = null;
  let positionIndicators = null;

  let rangeKey = "today";   // today | week | month | all
  let charts = {};
  let zoom = null;
  let tooltipLocked = false;
  // Same live-ticking "(2m ago)" as index.html's dashboard.js - see that
  // file's fmtRelativeTime for the reasoning; duplicated here rather
  // than shared since these two pages already each own their own boot/
  // load functions.
  let generatedAtMs = null;

  // text/grid read the live theme (assets/theme.js's data-theme attribute
  // on <html>) instead of a fixed value - the other colors here are all
  // saturated enough to read fine against either a dark or light page.
  function isLightTheme() {
    return document.documentElement.getAttribute("data-theme") === "light";
  }
  const COLORS = {
    combined: "#34d372",
    stock: "#6aa6ff",
    crypto: "#f0a63c",
    green: "#34d372",
    red: "#f0554a",
    gray: "#6b7280",
    get text() { return isLightTheme() ? "#4c5852" : "#9aa5a0"; },
    get grid() { return isLightTheme() ? "rgba(15,25,20,0.07)" : "rgba(255,255,255,0.06)"; },
  };

  // ---------------------------------------------------------------------
  // Safe fetch
  // ---------------------------------------------------------------------
  async function loadJson(name, fallback) {
    try {
      const res = await fetch(DATA_BASE + name, { cache: "no-store" });
      if (!res.ok) {
        console.warn(`[investingbot] ${name} responded with HTTP ${res.status} - using fallback.`);
        return fallback;
      }
      const text = await res.text();
      if (!text || !text.trim()) return fallback;
      try {
        return JSON.parse(text);
      } catch (parseErr) {
        console.warn(`[investingbot] ${name} was malformed JSON - using fallback.`, parseErr);
        return fallback;
      }
    } catch (networkErr) {
      console.warn(`[investingbot] ${name} could not be fetched - using fallback.`, networkErr);
      return fallback;
    }
  }

  // ---------------------------------------------------------------------
  // Formatting
  // ---------------------------------------------------------------------
  function isNum(v) { return typeof v === "number" && Number.isFinite(v); }
  function fmtUsd(v) {
    if (!isNum(v)) return "—";
    return (v < 0 ? "-" : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtUsdSigned(v) {
    if (!isNum(v)) return "—";
    return (v >= 0 ? "+" : "") + fmtUsd(v);
  }
  function fmtUsdAxis(v) {
    if (!isNum(v)) return "";
    const abs = Math.abs(v);
    return (v < 0 ? "-" : "") + "$" + abs.toLocaleString("en-US", { maximumFractionDigits: abs < 10 ? 2 : 0 });
  }
  function fmtPctSigned(v) {
    if (!isNum(v)) return "—";
    let digits = 2;
    if (v !== 0 && Math.abs(v) < 0.005) digits = 4;
    return (v >= 0 ? "+" : "") + v.toFixed(digits) + "%";
  }
  function fmtQty(v) {
    if (!isNum(v)) return "—";
    return v.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  function toDate(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function fmtDateET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric" }).format(d);
  }
  function fmtTimeET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true }).format(d) + " ET";
  }
  function fmtDateTimeET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    return `${fmtDateET(iso)} at ${fmtTimeET(iso)}`;
  }
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
  function axisLabel(iso, multiDay) {
    const d = toDate(iso);
    if (!d) return "";
    return new Intl.DateTimeFormat("en-US", multiDay
      ? { timeZone: "America/New_York", month: "short", day: "numeric" }
      : { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true }
    ).format(d);
  }
  function etDayKey(iso) {
    const d = toDate(iso);
    return d ? new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(d) : null;
  }

  // ---------------------------------------------------------------------
  // Range windows - read directly from dashboard.json's own periods
  // (today/week/month/all_time), the same reset-aware boundaries the
  // main dashboard's stat tiles use. Never recomputed independently, so
  // this page can't drift from the numbers next to it.
  // ---------------------------------------------------------------------
  const RANGE_TO_PERIOD = { today: "today", week: "week", month: "month", all: "all_time" };

  function currentPeriod() {
    return dashboard.periods[RANGE_TO_PERIOD[rangeKey]];
  }
  function rangeBounds() {
    const p = currentPeriod();
    const startMs = p.start_utc ? new Date(p.start_utc).getTime() : -Infinity;
    const endMs = p.end_utc ? new Date(p.end_utc).getTime() : Date.now();
    return { startMs, endMs, label: p.label };
  }

  function equityPoints() {
    return (equity && equity.available && Array.isArray(equity.points)) ? equity.points : [];
  }
  function confirmedSells(assetClass, startMs, endMs) {
    // Returns every confirmed sell in range, regardless of whether its
    // realized_pnl_usd is known - a sell with a missing cost basis (see
    // site_data.py/live_trade.py's fix in CHANGELOG) still genuinely
    // happened and must not silently disappear from "how many sells
    // were there," even though its own $ contribution can't be plotted.
    // Callers that need a plottable number filter to isNum(...) rows
    // themselves.
    if (!trades || !trades.available) return [];
    return trades.trades
      .filter((t) => {
        if (t.action !== "SELL" || t.order_status !== "confirmed_fill") return false;
        if (assetClass && t.asset_class !== assetClass) return false;
        const ts = toDate(t.timestamp_utc);
        return ts && ts.getTime() >= startMs && ts.getTime() <= endMs;
      })
      .sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  }

  // ---------------------------------------------------------------------
  // Custom HTML tooltip (Chart.js `external` handler) + crosshair
  // ---------------------------------------------------------------------
  const tipEl = () => document.getElementById("chart-tooltip");
  function hideTooltip() {
    const el = tipEl();
    if (!el) return;
    el.classList.remove("is-visible");
    el.setAttribute("aria-hidden", "true");
  }

  function externalTooltip(ctx) {
    const el = tipEl();
    if (!el) return;
    const model = ctx.tooltip;
    if (!model || model.opacity === 0) {
      if (!tooltipLocked) hideTooltip();
      return;
    }
    const meta = ctx.chart.$ibMeta || {};
    const idx = model.dataPoints && model.dataPoints.length ? model.dataPoints[0].dataIndex : null;
    if (idx === null || idx === undefined) return;
    const iso = (meta.stamps || [])[idx] || null;
    let html = "";

    // For a timeseries with a signed "value" (gain/loss vs. a baseline),
    // the swatch/border should reflect *this exact point's* sign, not a
    // fixed series color - otherwise a chart whose line changes color as
    // it crosses $0 would still show a swatch/border that never changes,
    // which is exactly what looked "always green" regardless of whether
    // the hovered point was actually up or down.
    let pointColor = null;
    if (meta.kind === "timeseries") {
      html += `<div class="tt-title">${meta.title || "Value"}</div>`;
      html += `<div class="tt-time">${iso ? fmtDateTimeET(iso) : "—"}</div>`;
      html += `<div class="tt-rows">`;
      (meta.series || []).forEach((s, di) => {
        if (!ctx.chart.isDatasetVisible(di)) return;
        const rec = s.records[idx];
        const swatchColor = rec && isNum(rec.value) ? (rec.value >= 0 ? COLORS.green : COLORS.red) : s.color;
        if (pointColor === null && rec && isNum(rec.value)) pointColor = swatchColor;
        html += `<div class="tt-series"><div class="tt-name"><span class="tt-swatch" style="background:${swatchColor}"></span>${s.label}</div>`;
        if (!rec || !isNum(rec.value)) {
          html += `<div class="tt-row"><span class="tt-label">Value</span><span class="tt-val muted">No recorded value</span></div>`;
        } else {
          if (isNum(rec.portfolio)) {
            html += `<div class="tt-row"><span class="tt-label">Portfolio value</span><span class="tt-val">${fmtUsd(rec.portfolio)}</span></div>`;
          }
          html += `<div class="tt-row"><span class="tt-label">${s.valueLabel}</span><span class="tt-val ${rec.value >= 0 ? "positive" : "negative"}">${fmtUsdSigned(rec.value)}</span></div>`;
          if (isNum(rec.pct)) {
            html += `<div class="tt-row"><span class="tt-label">${s.pctLabel || "Period return"}</span><span class="tt-val ${rec.pct >= 0 ? "positive" : "negative"}">${fmtPctSigned(rec.pct)}</span></div>`;
          }
          if (isNum(rec.delta)) {
            html += `<div class="tt-row"><span class="tt-label">Change</span><span class="tt-val ${rec.delta >= 0 ? "positive" : "negative"}">${fmtUsdSigned(rec.delta)}</span></div>`;
          } else {
            html += `<div class="tt-row"><span class="tt-label">Change</span><span class="tt-val muted">First sample in range</span></div>`;
          }
        }
        html += `</div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="tt-title">${model.title && model.title.length ? model.title[0] : (meta.title || "")}</div>`;
      html += `<div class="tt-rows">`;
      // For a win/loss breakdown, the border should reflect which
      // segment(s) are actually present at this ticker - a bar made
      // entirely of losses (e.g. hovering CAT with 0 wins, 1 loss) must
      // show red, not always fall back to the default green regardless
      // of what's actually being hovered.
      let hasWin = false, hasLoss = false, hasUnknown = false;
      model.dataPoints.forEach((dp) => {
        const raw = dp.raw;
        const fmt = meta.valueFormatter ? meta.valueFormatter(raw) : fmtUsdSigned(raw);
        // This is a trade *count* per dataset (Wins/Losses/Unknown), never
        // itself negative - coloring by raw >= 0 would make a "Losses: 1
        // trade" row read as positive/green just because 1 isn't below
        // zero. Color by which dataset the row belongs to instead, same
        // as the bars and legend swatches already do.
        const cls = !isNum(raw) ? "muted" : dp.dataset.label === "Losses" ? "negative" : dp.dataset.label === "Wins" ? "positive" : "muted";
        html += `<div class="tt-row"><span class="tt-label">${dp.dataset.label}</span><span class="tt-val ${cls}">${isNum(raw) ? fmt : "No recorded value"}</span></div>`;
        if (isNum(raw) && raw > 0) {
          if (dp.dataset.label === "Wins") hasWin = true;
          else if (dp.dataset.label === "Losses") hasLoss = true;
          else hasUnknown = true;
        }
      });
      html += `</div>`;
      if (hasLoss && !hasWin) pointColor = COLORS.red;
      else if (hasWin && !hasLoss) pointColor = COLORS.green;
      else if (hasUnknown && !hasWin && !hasLoss) pointColor = COLORS.gray;
      // else: a mix of wins and losses at this ticker - no single color
      // would be honest, so the border stays at its neutral default.
    }
    if (IS_TOUCH) {
      html += `<div class="tt-hint">${tooltipLocked ? "Tap elsewhere to dismiss" : "Tap a point to keep this open"}</div>`;
    }
    el.innerHTML = html;
    // Border matches the hovered point's own color - empty string falls
    // back to the CSS default (a neutral green) for charts with no
    // signed value at this point (e.g. a win/loss bar chart).
    el.style.borderColor = pointColor || "";
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
    id: "ibCrosshair",
    afterDatasetsDraw(chart) {
      const active = chart.tooltip && chart.tooltip.getActiveElements ? chart.tooltip.getActiveElements() : [];
      const area = chart.chartArea;
      if (!area) return;
      const ctx = chart.ctx;
      if (active.length) {
        const x = active[0].element.x;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, area.top);
        ctx.lineTo(x, area.bottom);
        ctx.lineWidth = 1;
        ctx.strokeStyle = "rgba(255,255,255,0.22)";
        ctx.stroke();
        ctx.restore();
      }
      const sel = chart.$ibDrag;
      if (sel && sel.active && isNum(sel.fromX) && isNum(sel.toX)) {
        ctx.save();
        ctx.fillStyle = "rgba(52,211,114,0.12)";
        ctx.fillRect(Math.min(sel.fromX, sel.toX), area.top, Math.abs(sel.toX - sel.fromX), area.bottom - area.top);
        ctx.restore();
      }
    },
  };

  // A slightly brighter horizontal line at y=0 on any chart whose scale
  // actually spans both positive and negative - the "breakeven" reference
  // a gain/loss chart is implicitly measuring against, made explicit
  // instead of left for the eye to find among the regular gridlines.
  // No-ops (and costs nothing) on a chart that never crosses zero.
  const zeroLinePlugin = {
    id: "ibZeroLine",
    beforeDatasetsDraw(chart) {
      const y = chart.scales.y;
      const area = chart.chartArea;
      if (!y || !area || y.min >= 0 || y.max <= 0) return;
      const py = y.getPixelForValue(0);
      const ctx = chart.ctx;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(area.left, py);
      ctx.lineTo(area.right, py);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255,255,255,0.16)";
      ctx.stroke();
      ctx.restore();
    },
  };

  function baseOptions(meta, extra) {
    const multiDay = !!meta.multiDay;
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: REDUCED_MOTION ? false : { duration: 220 },
      interaction: { mode: "index", intersect: false, axis: "x" },
      plugins: {
        legend: {
          display: meta.forceLegend === true || (meta.series || []).length > 1,
          position: "top",
          align: "start",
          labels: {
            color: COLORS.text, usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 14, font: { size: 11 },
            // Chart.js's default usePointStyle swatch reads the dataset's
            // *point* border/background (pointBorderColor etc.), which
            // several of our datasets never set explicitly (they only
            // style the line itself) - Chart.js then falls back to its
            // own default point border, which showed up as a mismatched
            // outline around the swatch that had nothing to do with the
            // line's actual color. Overridden here so the swatch is
            // always a single solid box in the dataset's own color
            // (green/red for the equity line, each series' own color
            // elsewhere) with no border at all.
            //
            // fontColor must also be set explicitly on every returned
            // item: a custom generateLabels bypasses Chart.js's own
            // default-label construction (which is what normally copies
            // labels.color onto each item), so without it Chart.js falls
            // through to the canvas context's own default fillStyle -
            // black - instead of this theme's actual legend text color.
            // That's the exact bug that made every legend's text
            // (equity chart, both win/loss bar charts) unreadable
            // against the dark background.
            generateLabels(chart) {
              return chart.data.datasets.map((ds, i) => {
                const color = ds.backgroundColor || ds.borderColor || COLORS.text;
                return {
                  text: ds.label,
                  fillStyle: color,
                  strokeStyle: color,
                  fontColor: COLORS.text,
                  lineWidth: 0,
                  pointStyle: "rectRounded",
                  hidden: !chart.isDatasetVisible(i),
                  datasetIndex: i,
                };
              });
            },
          },
          // Chart.js's default legend click toggles that dataset's
          // visibility - fine with several series, but on a
          // single-series chart (e.g. the equity line) it hides the
          // only thing there is to show, leaving a technically-empty
          // chart whose axis then autoscales to an arbitrary, confusing
          // range ("super zooms"). Never allow toggling off the last
          // dataset still visible in this chart, in any chart.
          onClick(_evt, legendItem, legend) {
            const chart = legend.chart;
            const index = legendItem.datasetIndex;
            const visibleCount = chart.data.datasets.filter((_, i) => chart.isDatasetVisible(i)).length;
            if (chart.isDatasetVisible(index)) {
              if (visibleCount <= 1) return;
              chart.hide(index);
              legendItem.hidden = true;
            } else {
              chart.show(index);
              legendItem.hidden = false;
            }
          },
        },
        tooltip: { enabled: false, external: externalTooltip },
      },
      scales: {
        x: {
          ticks: {
            color: COLORS.text, maxTicksLimit: meta.maxXTicks || 6, autoSkip: true, maxRotation: 0, minRotation: 0, font: { size: 10 },
            callback(value) {
              const iso = (meta.stamps || [])[value];
              return iso ? axisLabel(iso, multiDay) : "";
            },
          },
          grid: { color: COLORS.grid, drawTicks: false },
          border: { display: false },
        },
        y: {
          beginAtZero: meta.beginAtZero !== false,
          ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 6, callback: meta.yTick || fmtUsdAxis },
          grid: { color: COLORS.grid, drawTicks: false },
          border: { display: false },
        },
      },
    }, extra || {});
  }

  function destroyChart(key) { if (charts[key]) { charts[key].destroy(); delete charts[key]; } }
  function setEmpty(chartId, message) {
    const wrap = document.getElementById(chartId + "-wrap");
    const empty = document.getElementById(chartId + "-empty");
    const isEmpty = message !== null;
    if (wrap) wrap.hidden = isEmpty;
    if (empty) { empty.hidden = !isEmpty; if (isEmpty) empty.innerHTML = message; }
  }
  function setSummary(chartId, text) {
    const el = document.getElementById(chartId + "-summary");
    if (el) el.textContent = text || "";
  }
  // Same as setSummary, but takes pre-built HTML - only ever used with
  // our own formatted numbers (fmtUsdSigned/fmtPctSigned), never with
  // raw/untrusted strings, so no escaping is needed here.
  function setSummaryHtml(chartId, html) {
    const el = document.getElementById(chartId + "-summary");
    if (el) el.innerHTML = html || "";
  }
  function unrealizedNote(assetClass) {
    const p = currentPeriod();
    const v = assetClass ? (p.unrealized_pnl_by_asset_class || {})[assetClass] : p.unrealized_pnl_usd;
    if (!isNum(v)) return "";
    return `<p class="chart-empty-note ${v >= 0 ? "positive" : "negative"}">Live unrealized P&amp;L on open positions: ${fmtUsdSigned(v)}</p>`;
  }
  function lastRecordedIso() {
    const pts = equityPoints();
    return pts.length ? pts[pts.length - 1].timestamp_utc : null;
  }
  function lastSampleNote() {
    const iso = lastRecordedIso();
    return iso ? `<p>Most recent recorded sample: ${fmtDateTimeET(iso)}. Try a wider range above.</p>` : "";
  }
  function lastSampleText() {
    const iso = lastRecordedIso();
    return iso ? ` Most recent recorded sample was ${fmtDateTimeET(iso)}.` : "";
  }

  // ---------------------------------------------------------------------
  // Panel 1: net account gain/loss - whole account, one line, exactly
  // mirroring visualize_log.py panel 1 (baseline is the period's own
  // starting_value_usd, already reset-anchored server-side).
  // ---------------------------------------------------------------------
  function renderEquityChart() {
    const canvas = document.getElementById("chart-equity");
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart("equity");

    const p = currentPeriod();
    const { startMs, endMs, label } = rangeBounds();
    const baseline = p.starting_value_usd;
    const pts = equityPoints().filter((pt) => {
      const d = toDate(pt.timestamp_utc);
      return d && d.getTime() >= startMs && d.getTime() <= endMs;
    });

    if (!isNum(baseline) || !pts.length) {
      setEmpty("chart-equity", `<p>No equity history recorded for ${label.toLowerCase()}.</p>${lastSampleNote()}`);
      setSummary("chart-equity", `No recorded equity history for ${label.toLowerCase()}.${lastSampleText()}`);
      return;
    }
    setEmpty("chart-equity", null);

    const stamps = pts.map((pt) => pt.timestamp_utc);
    let prev = null;
    const records = pts.map((pt) => {
      const gain = pt.portfolio_value_usd - baseline;
      const rec = { value: gain, portfolio: pt.portfolio_value_usd, pct: baseline ? (pt.portfolio_value_usd / baseline - 1) * 100 : null, delta: prev === null ? null : pt.portfolio_value_usd - prev };
      prev = pt.portfolio_value_usd;
      return rec;
    });
    const multiDay = new Set(stamps.map(etDayKey)).size > 1;
    const finalPositive = records[records.length - 1].value >= 0;
    const trendColor = finalPositive ? COLORS.green : COLORS.red;
    // Per-point color, not one fixed color for the whole line - a
    // segment is green when the point it's heading *to* is above the
    // $0 baseline, red when it's below, so the line actually reflects
    // where the account was at each point in time, not just where it
    // ended up.
    const pointColor = (i) => (records[i].value >= 0 ? COLORS.green : COLORS.red);
    const segmentColor = (ctx) => (ctx.p1.parsed.y >= 0 ? COLORS.green : COLORS.red);
    const meta = {
      kind: "timeseries", title: "Whole Account", stamps, multiDay, maxXTicks: 7, beginAtZero: false, yTick: fmtUsdAxis, forceLegend: true,
      series: [{ key: "combined", label: `Net gain/loss vs. ${fmtUsd(baseline)} baseline`, color: trendColor, valueLabel: "Gain / loss vs. baseline", pctLabel: "Period return", records }],
    };
    charts.equity = new Chart(canvas, {
      type: "line",
      data: {
        labels: stamps.map((_, i) => i),
        datasets: [{
          label: meta.series[0].label,
          data: records.map((r) => r.value),
          borderColor: trendColor,
          // Legend swatch reads backgroundColor, not borderColor, for its
          // fill - set explicitly (fill:false below means it's otherwise
          // unused) so the legend always shows one clear, deterministic
          // color matching the account's current direction, never a
          // library default unrelated to up/down.
          backgroundColor: trendColor,
          segment: { borderColor: segmentColor },
          // Line color only - no shaded area under the curve, it makes
          // the chart harder to read at a glance.
          fill: false,
          borderWidth: 2,
          tension: 0.18,
          pointRadius: 0,
          pointBackgroundColor: (ctx) => pointColor(ctx.dataIndex),
          pointHoverRadius: 5,
          pointHoverBackgroundColor: (ctx) => pointColor(ctx.dataIndex),
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: "#050706",
          spanGaps: false,
        }],
      },
      options: baseOptions(meta),
      plugins: [crosshairPlugin, zeroLinePlugin],
    });
    charts.equity.$ibMeta = meta;
    if (zoom) { charts.equity.options.scales.x.min = zoom.min; charts.equity.options.scales.x.max = zoom.max; charts.equity.update("none"); }
    attachInteractions(charts.equity, meta);

    // The card's hover outline matches the line's own direction (green
    // up, red down) instead of always reading green regardless of
    // whether the account is actually up or down.
    const card = canvas.closest(".chart-card");
    if (card) {
      card.classList.toggle("trend-up", finalPositive);
      card.classList.toggle("trend-down", !finalPositive);
    }

    const last = records[records.length - 1];
    const trendClass = finalPositive ? "positive" : "negative";
    setSummaryHtml("chart-equity", `${label}: ${records.length} recorded sample${records.length === 1 ? "" : "s"} from ${fmtDateTimeET(stamps[0])} to ${fmtDateTimeET(stamps[stamps.length - 1])}, ` +
      `now <span class="${trendClass}">${fmtUsdSigned(last.value)}${isNum(last.pct) ? ` (${fmtPctSigned(last.pct)})` : ""}</span>. Baseline ${fmtUsd(baseline)}` +
      (p.starting_value_asof_utc ? ` as of ${fmtDateTimeET(p.starting_value_asof_utc)}` : "") + (p.trade_log_reset_during_period ? " (anchored to the most recent relaunch)." : "."));
    syncZoomUi();
  }

  function attachInteractions(chart, meta) {
    const canvas = chart.canvas;
    if (IS_TOUCH) {
      // Lock on touchstart, NOT click: the browser's synthetic click
      // after a tap fires after Chart.js already dispatched a hide, so
      // locking on click made tapping a point appear to do nothing.
      ["touchstart", "click"].forEach((ev) => canvas.addEventListener(ev, () => { tooltipLocked = true; }, { passive: true }));
    } else {
      canvas.addEventListener("mouseleave", () => { if (!tooltipLocked) hideTooltip(); });
    }
    if (!IS_TOUCH && meta.kind === "timeseries" && (meta.stamps || []).length > 12) {
      chart.$ibDrag = { active: false, fromX: null, toX: null, fromIdx: null };
      const idxAt = (evt) => {
        const rect = canvas.getBoundingClientRect();
        const x = evt.clientX - rect.left;
        const area = chart.chartArea;
        if (!area || x < area.left || x > area.right) return null;
        return Math.round(chart.scales.x.getValueForPixel(x));
      };
      canvas.addEventListener("mousedown", (e) => {
        const i = idxAt(e);
        if (i === null) return;
        chart.$ibDrag = { active: true, fromX: e.clientX - canvas.getBoundingClientRect().left, toX: null, fromIdx: i };
      });
      canvas.addEventListener("mousemove", (e) => {
        if (!chart.$ibDrag || !chart.$ibDrag.active) return;
        chart.$ibDrag.toX = e.clientX - canvas.getBoundingClientRect().left;
        chart.draw();
      });
      window.addEventListener("mouseup", (e) => {
        if (!chart.$ibDrag || !chart.$ibDrag.active) return;
        const endIdx = idxAt(e);
        const startIdx = chart.$ibDrag.fromIdx;
        chart.$ibDrag = { active: false, fromX: null, toX: null, fromIdx: null };
        if (endIdx === null || startIdx === null) { chart.draw(); return; }
        const lo = Math.max(0, Math.min(startIdx, endIdx));
        const hi = Math.min((meta.stamps.length - 1), Math.max(startIdx, endIdx));
        if (hi - lo < 2) { chart.draw(); return; }
        zoom = { min: lo, max: hi };
        chart.options.scales.x.min = lo;
        chart.options.scales.x.max = hi;
        chart.update("none");
        syncZoomUi();
      });
    }
  }

  function syncZoomUi() {
    const btn = document.getElementById("reset-zoom");
    if (btn) btn.hidden = !zoom;
    const cap = document.getElementById("range-caption");
    if (!cap) return;
    const { label } = rangeBounds();
    const meta = charts.equity && charts.equity.$ibMeta;
    if (zoom && meta && meta.stamps) {
      cap.textContent = `${label} — zoomed to ${fmtDateTimeET(meta.stamps[zoom.min])} → ${fmtDateTimeET(meta.stamps[zoom.max])}`;
    } else if (meta && meta.stamps && meta.stamps.length) {
      cap.textContent = `${label} — ${meta.stamps.length} recorded samples`;
    } else {
      cap.textContent = label;
    }
  }

  // ---------------------------------------------------------------------
  // Panels 2/3 and 4/5: per-asset-class cumulative realized P&L and
  // win/loss - identical logic, called once per class (crypto, stock),
  // exactly mirroring visualize_log.py's plot_cumulative_pnl/plot_win_loss.
  // ---------------------------------------------------------------------
  function renderClassCumPnl(assetClass, chartId, chartKey, color) {
    const canvas = document.getElementById(chartId);
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart(chartKey);
    const { startMs, endMs, label } = rangeBounds();
    const sells = confirmedSells(assetClass, startMs, endMs);
    const nice = assetClass === "stock" ? "stock" : "crypto";
    if (!sells.length) {
      setEmpty(chartId, `<p>No executed ${nice} sell trades in this range.</p>${unrealizedNote(assetClass)}`);
      setSummary(chartId, `No confirmed ${nice} sells recorded for ${label.toLowerCase()}, so there is no realized P&L to plot.`);
      return;
    }
    // A sell can be confirmed but still have no computable P&L (its
    // cost basis was never recorded - see CHANGELOG). It's still a real
    // sell, so it must never make this look like "no trades happened" -
    // just excluded from the cumulative total it can't contribute a
    // number to.
    const known = sells.filter((t) => isNum(t.realized_pnl_usd));
    const unknownCount = sells.length - known.length;
    if (!known.length) {
      setEmpty(chartId, `<p>${sells.length} confirmed ${nice} sell${sells.length === 1 ? "" : "s"} recorded for ${label.toLowerCase()}, but none has a recorded cost basis, so realized P&L can't be computed yet.</p>${unrealizedNote(assetClass)}`);
      setSummary(chartId, `${label}: ${sells.length} confirmed ${nice} sell${sells.length === 1 ? "" : "s"}, but cost basis wasn't recorded for any of them, so cumulative realized P&L can't be computed.`);
      return;
    }
    setEmpty(chartId, null);
    let running = 0, prev = null;
    const stamps = [], records = [];
    known.forEach((t) => {
      running += t.realized_pnl_usd;
      stamps.push(t.timestamp_utc);
      records.push({ value: running, portfolio: null, pct: null, delta: prev === null ? null : running - prev });
      prev = running;
    });
    const multiDay = new Set(stamps.map(etDayKey)).size > 1;
    const meta = {
      kind: "timeseries", title: assetClass === "stock" ? "Stocks — cumulative realized P&L" : "Crypto — cumulative realized P&L",
      stamps, multiDay, maxXTicks: 5, beginAtZero: true, yTick: fmtUsdAxis,
      series: [{ key: assetClass, label: `${assetClass === "stock" ? "Stocks" : "Crypto"} (realized)`, color, valueLabel: "Cumulative realized P&L", records }],
    };
    charts[chartKey] = new Chart(canvas, {
      type: "line",
      data: {
        labels: stamps.map((_, i) => i),
        datasets: [{
          label: `${assetClass === "stock" ? "Stocks" : "Crypto"} realized P&L`,
          data: records.map((r) => r.value),
          borderColor: color, backgroundColor: color, borderWidth: 2,
          stepped: "after", fill: false, pointRadius: 3, pointHoverRadius: 6, spanGaps: false,
        }],
      },
      options: baseOptions(meta),
      plugins: [crosshairPlugin, zeroLinePlugin],
    });
    charts[chartKey].$ibMeta = meta;
    setSummary(chartId, `${label}: ${known.length} confirmed ${nice} sell${known.length === 1 ? "" : "s"}` +
      (unknownCount ? ` (${unknownCount} more with no recorded cost basis, excluded from this total)` : "") +
      `, ending at ${fmtUsdSigned(running)} cumulative realized P&L (last fill ${fmtDateTimeET(stamps[stamps.length - 1])}).`);
  }

  function renderClassWinLoss(assetClass, chartId, chartKey) {
    const canvas = document.getElementById(chartId);
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart(chartKey);
    const { startMs, endMs, label } = rangeBounds();
    const sells = confirmedSells(assetClass, startMs, endMs);
    const nice = assetClass === "stock" ? "stock" : "crypto";
    if (!sells.length) {
      setEmpty(chartId, `<p>No executed ${nice} sell trades in this range.</p>${unrealizedNote(assetClass)}`);
      setSummary(chartId, `No confirmed ${nice} sells recorded for ${label.toLowerCase()}, so there is no win/loss split to plot.`);
      return;
    }
    setEmpty(chartId, null);
    // A confirmed sell can still have no computable P&L if its cost
    // basis was never recorded (see CHANGELOG). Rather than miscounting
    // it as a loss (JS's `null <= 0` is true) or dropping it from the
    // chart entirely, it gets its own gray "Unknown P&L" bar per ticker -
    // still a real, visible bar, just honestly labeled as unknown.
    const tickers = Array.from(new Set(sells.map((t) => t.ticker))).sort();
    const wins = tickers.map((tk) => sells.filter((t) => t.ticker === tk && isNum(t.realized_pnl_usd) && t.realized_pnl_usd > 0).length);
    const losses = tickers.map((tk) => sells.filter((t) => t.ticker === tk && isNum(t.realized_pnl_usd) && t.realized_pnl_usd <= 0).length);
    const unknown = tickers.map((tk) => sells.filter((t) => t.ticker === tk && !isNum(t.realized_pnl_usd)).length);
    const unknownCount = unknown.reduce((a, b) => a + b, 0);
    const datasets = [
      { label: "Wins", data: wins, backgroundColor: COLORS.green, borderRadius: 3 },
      { label: "Losses", data: losses, backgroundColor: COLORS.red, borderRadius: 3 },
    ];
    if (unknownCount) {
      datasets.push({ label: "Unknown P&L (no cost basis)", data: unknown, backgroundColor: COLORS.gray, borderRadius: 3 });
    }
    charts[chartKey] = new Chart(canvas, {
      type: "bar",
      data: { labels: tickers, datasets },
      options: baseOptions({ forceLegend: true }, {
        scales: {
          x: { stacked: true, ticks: { color: COLORS.text, font: { size: 10 }, maxRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: { stacked: true, beginAtZero: true, ticks: { color: COLORS.text, font: { size: 10 }, precision: 0, maxTicksLimit: 5 }, grid: { color: COLORS.grid, drawTicks: false }, border: { display: false } },
        },
      }),
      plugins: [crosshairPlugin],
    });
    charts[chartKey].$ibMeta = { kind: "bar", title: `${assetClass === "stock" ? "Stocks" : "Crypto"} win/loss`, valueFormatter: (v) => `${v} trade${v === 1 ? "" : "s"}` };
    const totalW = wins.reduce((a, b) => a + b, 0), totalL = losses.reduce((a, b) => a + b, 0);
    setSummary(chartId, `${label}: ${totalW} winning and ${totalL} losing confirmed ${nice} sells across ${tickers.length} ticker${tickers.length === 1 ? "" : "s"} (${tickers.join(", ")})` +
      (unknownCount ? ` - ${unknownCount} more sell${unknownCount === 1 ? "" : "s"} with unknown P&L (no recorded cost basis)` : "") + `.`);
  }

  // ---------------------------------------------------------------------
  // Panels 6/7: current open positions, crypto and stocks - only
  // populated when the workflow ran with --live-positions; otherwise
  // says so rather than showing stale or fabricated numbers.
  // ---------------------------------------------------------------------
  // Same reasoning as dashboard.js's positionSmaRow: rule_based/
  // ml_filtered positions sell on a mean-reversion recovery vs. their
  // own 20-period SMA, not vs. entry price - a number the unrealized
  // P&L row below doesn't capture. day_trading (crypto) positions sell
  // on gain-vs-entry instead, already shown by that row, so this stays
  // empty for them rather than showing a second, unrelated number.
  function positionSmaRow(p) {
    if (p.strategy !== "rule_based" && p.strategy !== "ml_filtered") return "";
    if (!positionIndicators || !positionIndicators.available) return "";
    const ind = positionIndicators.symbols ? positionIndicators.symbols[p.symbol] : null;
    if (!ind) return "";
    const threshold = ind.exit_threshold;
    if (!ind.available || ind.pct_vs_sma20 === null || ind.pct_vs_sma20 === undefined) {
      return `<div class="position-card-row position-card-sma"><span>vs 20-bar avg</span><span>—</span></div>`;
    }
    const cls = ind.pct_vs_sma20 >= 0 ? "positive" : "negative";
    const label = isNum(threshold)
      ? `${fmtPctSigned(ind.pct_vs_sma20 * 100)} (sells at ${fmtPctSigned(threshold * 100)})`
      : fmtPctSigned(ind.pct_vs_sma20 * 100);
    return `<div class="position-card-row position-card-sma"><span>vs 20-bar avg</span><span class="${cls}">${label}</span></div>`;
  }

  // Same small sparkline renderer index.html's dashboard.js draws its
  // own position/tracker cards with (see that file's sparklineSvg) -
  // duplicated here rather than shared since these two pages already
  // each build their own independent positionCard(). Omitted entirely
  // when a ticker's own spark fetch failed server-side, never drawn as
  // a fabricated flat line.
  function sparkSvg(values) {
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
    const color = values[values.length - 1] >= values[0] ? COLORS.green : COLORS.red;
    const area = `${pad},${h - pad} ${pts.join(" ")} ${w - pad},${h - pad}`;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">` +
      `<polyline points="${area}" fill="${color}" fill-opacity="0.1" stroke="none"></polyline>` +
      `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" ` +
      `stroke-linejoin="round" stroke-linecap="round"></polyline></svg>`;
  }
  // Same "what is this" ambiguity index.html's dashboard.js flags on its
  // own version of this card - see that file's SPARK_TOOLTIP comment.
  const SPARK_TOOLTIP = "Last ~45 days of daily closes - not since purchase, not an average";
  function cardSparkHtml(spark) {
    if (!Array.isArray(spark) || spark.length < 2) return "";
    return `<div class="position-card-spark" data-tooltip="${SPARK_TOOLTIP}" aria-label="${SPARK_TOOLTIP}">${sparkSvg(spark)}</div>`;
  }

  function positionCard(p) {
    const pnl = p.unrealized_pl;
    const trend = pnl > 0 ? "trend-up" : pnl < 0 ? "trend-down" : "";
    // data-symbol is the bare ticker (p.ticker, e.g. "BTC" - not
    // Alpaca's own "BTCUSD") so assets/position-chart.js (a separate,
    // shared script) can open this exact ticker's range-selectable
    // price chart on click by keying straight into ticker_charts.json -
    // same markup contract as index.html's own positionCard() in
    // dashboard.js, so one shared script handles every card sitewide.
    return `
      <div class="position-card ${trend}" data-symbol="${p.ticker}" data-is-crypto="${p.is_crypto}" tabindex="0" role="button" aria-haspopup="dialog">
        <div class="position-card-head">
          <span class="position-card-ticker">${p.symbol}</span>
          <span class="position-card-strategy strategy-${p.strategy || "unknown"}">${p.strategy || "unknown"}</span>
        </div>
        ${cardSparkHtml(p.spark)}
        <div class="position-card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="position-card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="position-card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="position-card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        ${positionSmaRow(p)}
        <div class="position-card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPctSigned(p.unrealized_plpc * 100)})</div>
        <div class="position-card-hint">View price history →</div>
      </div>`;
  }

  function renderPositionsPanel(assetClass, elId) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (!positions || !positions.available) {
      el.innerHTML = `<p class="empty-state">${(positions && positions.reason) || "Live positions weren't fetched for this run."}</p>`;
      return;
    }
    const list = positions.positions.filter((p) => (assetClass === "crypto" ? p.is_crypto : !p.is_crypto));
    el.innerHTML = list.length ? list.map(positionCard).join("") : `<p class="empty-state">No open ${assetClass === "crypto" ? "crypto" : "stock"} positions right now.</p>`;
  }

  // ---------------------------------------------------------------------
  // Orchestration
  // ---------------------------------------------------------------------
  function renderAll() {
    hideTooltip();
    tooltipLocked = false;
    renderEquityChart();
    renderClassCumPnl("crypto", "chart-crypto-cum-pnl", "cryptoCumPnl", COLORS.crypto);
    renderClassWinLoss("crypto", "chart-crypto-winloss", "cryptoWinLoss");
    renderClassCumPnl("stock", "chart-stock-cum-pnl", "stockCumPnl", COLORS.stock);
    renderClassWinLoss("stock", "chart-stock-winloss", "stockWinLoss");
    renderPositionsPanel("crypto", "positions-crypto");
    renderPositionsPanel("stock", "positions-stock");
  }

  function safely(label, fn) {
    try { fn(); } catch (err) { console.error(`[investingbot] ${label} failed:`, err); }
  }

  function boot() {
    document.querySelectorAll("#range-control button").forEach((btn) => {
      btn.addEventListener("click", () => {
        rangeKey = btn.dataset.range;
        zoom = null;
        document.querySelectorAll("#range-control button").forEach((b) => b.classList.toggle("active", b === btn));
        safely("range change", renderAll);
      });
    });
    const rz = document.getElementById("reset-zoom");
    if (rz) rz.addEventListener("click", () => {
      zoom = null;
      if (charts.equity) {
        delete charts.equity.options.scales.x.min;
        delete charts.equity.options.scales.x.max;
        charts.equity.update("none");
      }
      syncZoomUi();
    });
    document.addEventListener("click", (e) => {
      if (tooltipLocked && e.target.tagName !== "CANVAS") { tooltipLocked = false; hideTooltip(); }
    });
    window.addEventListener("resize", () => { hideTooltip(); tooltipLocked = false; });

    const backToTop = document.getElementById("back-to-top");
    if (backToTop) {
      window.addEventListener("scroll", () => {
        backToTop.classList.toggle("is-visible", window.scrollY > 600);
      }, { passive: true });
      backToTop.addEventListener("click", () => {
        window.scrollTo({ top: 0, behavior: REDUCED_MOTION ? "auto" : "smooth" });
      });
    }

    setupScrollReveal();
    load();

    // Every chart here is built from data already loaded once (dashboard/
    // trades/equity/positions), so a theme flip just needs a redraw with
    // the new text/grid colors, not a re-fetch.
    document.addEventListener("ib:theme-changed", () => {
      if (typeof Chart !== "undefined") Chart.defaults.color = COLORS.text;
      if (dashboard) safely("charts", renderAll);
    });
  }

  // Each account/crypto/stocks section eases in as it's scrolled into
  // view, rather than all being visible (or all invisible) at once.
  // Doesn't gate access to anything: falls back to showing every
  // section immediately if IntersectionObserver isn't supported, and
  // skips the transition (shows immediately) under reduced motion.
  function setupScrollReveal() {
    const groups = document.querySelectorAll(".chart-section-group");
    if (!groups.length) return;
    if (REDUCED_MOTION || !("IntersectionObserver" in window)) {
      groups.forEach((g) => g.classList.add("is-visible"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -60px 0px" });
    groups.forEach((g) => io.observe(g));
  }

  async function load() {
    [dashboard, trades, equity, positions, positionIndicators] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
      loadJson("position_indicators.json", { available: false, symbols: {} }),
    ]);

    if (!dashboard) {
      document.getElementById("charts-app").innerHTML =
        '<p class="empty-state" style="text-align:center;padding:60px 0;">' +
        "The dashboard data hasn't loaded yet - dashboard.json is missing or unreadable. " +
        "Once the update-dashboard workflow runs, this page will populate automatically.</p>";
      return;
    }

    const lu = document.getElementById("last-updated");
    if (lu) lu.textContent = `Last updated: ${fmtDateTimeET(dashboard.generated_at_utc)}`;
    generatedAtMs = new Date(dashboard.generated_at_utc).getTime();
    tickLastUpdatedRelative();
    setInterval(tickLastUpdatedRelative, 30000);
    const note = document.getElementById("data-note");
    if (note) {
      note.textContent =
        "Note on Stocks vs. Crypto: the stock and crypto workflows each log the whole account's value, not a separate per-asset-class " +
        "balance, so a historical portfolio value split by asset class doesn't exist in the logs and isn't estimated here. The Crypto/Stocks " +
        "charts show cumulative realized P&L from confirmed sell fills, which is genuinely per-class and timestamped.";
    }
    safely("charts", renderAll);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
