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

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const IS_TOUCH = window.matchMedia("(hover: none)").matches;

  let dashboard = null;
  let trades = null;
  let equity = null;
  let positions = null;

  let rangeKey = "today";   // today | week | month | all
  let charts = {};
  let zoom = null;
  let tooltipLocked = false;

  const COLORS = {
    combined: "#34d372",
    stock: "#6aa6ff",
    crypto: "#f0a63c",
    green: "#34d372",
    red: "#f0554a",
    text: "#9aa5a0",
    grid: "rgba(255,255,255,0.06)",
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
    if (!trades || !trades.available) return [];
    return trades.trades
      .filter((t) => {
        if (t.action !== "SELL" || t.order_status !== "confirmed_fill" || !isNum(t.realized_pnl_usd)) return false;
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

    if (meta.kind === "timeseries") {
      html += `<div class="tt-title">${meta.title || "Value"}</div>`;
      html += `<div class="tt-time">${iso ? fmtDateTimeET(iso) : "—"}</div>`;
      html += `<div class="tt-rows">`;
      (meta.series || []).forEach((s, di) => {
        if (!ctx.chart.isDatasetVisible(di)) return;
        const rec = s.records[idx];
        html += `<div class="tt-series"><div class="tt-name"><span class="tt-swatch" style="background:${s.color}"></span>${s.label}</div>`;
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
      model.dataPoints.forEach((dp) => {
        const raw = dp.raw;
        const fmt = meta.valueFormatter ? meta.valueFormatter(raw) : fmtUsdSigned(raw);
        const cls = !isNum(raw) ? "muted" : raw >= 0 ? "positive" : "negative";
        html += `<div class="tt-row"><span class="tt-label">${dp.dataset.label}</span><span class="tt-val ${cls}">${isNum(raw) ? fmt : "No recorded value"}</span></div>`;
      });
      html += `</div>`;
    }
    if (IS_TOUCH) {
      html += `<div class="tt-hint">${tooltipLocked ? "Tap elsewhere to dismiss" : "Tap a point to keep this open"}</div>`;
    }
    el.innerHTML = html;
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
          labels: { color: COLORS.text, usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 14, font: { size: 11 } },
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
      plugins: [crosshairPlugin],
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
    setEmpty(chartId, null);
    let running = 0, prev = null;
    const stamps = [], records = [];
    sells.forEach((t) => {
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
      plugins: [crosshairPlugin],
    });
    charts[chartKey].$ibMeta = meta;
    setSummary(chartId, `${label}: ${sells.length} confirmed ${nice} sell${sells.length === 1 ? "" : "s"}, ending at ${fmtUsdSigned(running)} cumulative realized P&L (last fill ${fmtDateTimeET(stamps[stamps.length - 1])}).`);
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
    const tickers = Array.from(new Set(sells.map((t) => t.ticker))).sort();
    const wins = tickers.map((tk) => sells.filter((t) => t.ticker === tk && t.realized_pnl_usd > 0).length);
    const losses = tickers.map((tk) => sells.filter((t) => t.ticker === tk && t.realized_pnl_usd <= 0).length);
    charts[chartKey] = new Chart(canvas, {
      type: "bar",
      data: { labels: tickers, datasets: [
        { label: "Wins", data: wins, backgroundColor: COLORS.green, borderRadius: 3 },
        { label: "Losses", data: losses, backgroundColor: COLORS.red, borderRadius: 3 },
      ] },
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
    setSummary(chartId, `${label}: ${totalW} winning and ${totalL} losing confirmed ${nice} sells across ${tickers.length} ticker${tickers.length === 1 ? "" : "s"} (${tickers.join(", ")}).`);
  }

  // ---------------------------------------------------------------------
  // Panels 6/7: current open positions, crypto and stocks - only
  // populated when the workflow ran with --live-positions; otherwise
  // says so rather than showing stale or fabricated numbers.
  // ---------------------------------------------------------------------
  function positionCard(p) {
    const pnl = p.unrealized_pl;
    const trend = pnl > 0 ? "trend-up" : pnl < 0 ? "trend-down" : "";
    return `
      <div class="position-card ${trend}">
        <div class="position-card-head">
          <span class="position-card-ticker">${p.symbol}</span>
          <span class="position-card-strategy">${p.strategy || "unknown"}</span>
        </div>
        <div class="position-card-row"><span>Qty</span><span>${fmtQty(p.qty)}</span></div>
        <div class="position-card-row"><span>Avg Entry</span><span>${fmtUsd(p.avg_entry_price)}</span></div>
        <div class="position-card-row"><span>Current</span><span>${fmtUsd(p.current_price)}</span></div>
        <div class="position-card-row"><span>Mkt Value</span><span>${fmtUsd(p.market_value)}</span></div>
        <div class="position-card-pnl ${pnl >= 0 ? "positive" : "negative"}">${fmtUsdSigned(pnl)} (${fmtPctSigned(p.unrealized_plpc * 100)})</div>
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

    load();
  }

  async function load() {
    [dashboard, trades, equity, positions] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
      loadJson("positions.json", { available: false, reason: "positions.json not found", positions: [] }),
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
