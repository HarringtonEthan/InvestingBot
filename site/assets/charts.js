/*
 * InvestingBot - interactive charts page (charts.html).
 *
 * Split out of dashboard.js so the main dashboard never has to load
 * Chart.js at all. This file owns every chart and nothing else.
 *
 * ACCURACY RULES enforced throughout (see also site_data.py):
 *  - A tooltip's timestamp and its values always come from the same
 *    underlying record. Series are aligned on a shared, sorted list of
 *    REAL sample timestamps; a series with no sample at a given
 *    timestamp gets `null`, which Chart.js renders as a gap and the
 *    tooltip renders as "No recorded value". Missing data is never
 *    coerced to zero and points are never interpolated or invented.
 *  - Realized P&L only ever comes from confirmed-fill SELL rows, the
 *    same definition site_data.py uses server-side.
 *  - The period baseline mirrors site_data.py's summarize_period()
 *    reset/relaunch anchoring exactly, so the chart can't disagree with
 *    the numbers on the main dashboard.
 *
 * A note on the Stocks/Crypto category split: equity_log_stocks.csv and
 * equity_log_crypto.csv both record the WHOLE ACCOUNT's value (they're
 * two workflows logging one Alpaca account, not two separate books) -
 * verified directly against the logs. So a historical portfolio value
 * split by asset class does not exist and is NOT invented here. What is
 * genuinely per-class and timestamped is realized P&L from confirmed
 * sells, so that's what the per-class series show, labeled as such.
 */

(function () {
  "use strict";

  const DATA_BASE = "data/";
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const IS_TOUCH = window.matchMedia("(hover: none)").matches;

  let dashboard = null;
  let trades = null;
  let equity = null;

  let rangeKey = "today";
  let category = "combined";
  let charts = {};
  let zoom = null;          // {min, max} index bounds on the equity chart, or null
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
  // Formatting. Currency $12,345.67 / percent +2.48% / 2:35 PM ET /
  // July 28, 2026. Nothing here can emit NaN, undefined, or an invalid
  // date - callers get a clean em dash instead.
  // ---------------------------------------------------------------------
  function isNum(v) {
    return typeof v === "number" && Number.isFinite(v);
  }
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
    // Axis ticks drop cents (tooltips keep full precision).
    return (v < 0 ? "-" : "") + "$" + abs.toLocaleString("en-US", { maximumFractionDigits: abs < 10 ? 2 : 0 });
  }
  function fmtPctSigned(v) {
    if (!isNum(v)) return "—";
    // Two decimals normally (+2.48%). But a genuinely non-zero move
    // smaller than a hundredth of a percent would round to "+0.00%" and
    // read as "nothing happened", so those get extra precision rather
    // than being flattened to a misleading zero.
    let digits = 2;
    if (v !== 0 && Math.abs(v) < 0.005) digits = 4;
    return (v >= 0 ? "+" : "") + v.toFixed(digits) + "%";
  }
  function fmtPctAxis(v) {
    if (!isNum(v)) return "";
    return v.toFixed(Math.abs(v) < 1 ? 2 : 1) + "%";
  }
  function toDate(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function fmtDateET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric",
    }).format(d);
  }
  function fmtTimeET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    const t = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true,
    }).format(d);
    return t + " ET";
  }
  function fmtDateTimeET(iso) {
    const d = toDate(iso);
    if (!d) return "—";
    return `${fmtDateET(iso)} at ${fmtTimeET(iso)}`;
  }
  // Axis labels: time-only while a range stays inside one ET day,
  // date-only once it spans several. This is what stops the drawdown
  // chart's axis from stacking a dozen long "Jul 28, 03:05 AM ET"
  // labels on top of each other.
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
    if (!d) return null;
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(d);
  }

  // ---------------------------------------------------------------------
  // Range windows. Today uses the same ET-calendar boundary the server
  // computed; 7d/30d are true rolling windows measured back from the
  // generation time; All Time has no lower bound.
  // ---------------------------------------------------------------------
  function rangeBounds() {
    const nowIso = dashboard.generated_at_utc;
    const nowMs = toDate(nowIso) ? toDate(nowIso).getTime() : Date.now();
    if (rangeKey === "today") {
      const start = dashboard.periods.today.start_utc;
      return { startMs: start ? new Date(start).getTime() : -Infinity, endMs: nowMs, label: "Today" };
    }
    if (rangeKey === "7d") return { startMs: nowMs - 7 * 864e5, endMs: nowMs, label: "Last 7 days" };
    if (rangeKey === "30d") return { startMs: nowMs - 30 * 864e5, endMs: nowMs, label: "Last 30 days" };
    return { startMs: -Infinity, endMs: nowMs, label: "All time" };
  }

  function equityPoints() {
    return (equity && equity.available && Array.isArray(equity.points)) ? equity.points : [];
  }

  function confirmedSells(assetClass, startMs, endMs) {
    if (!trades || !trades.available) return [];
    return trades.trades
      .filter((t) => {
        if (t.action !== "SELL" || t.order_status !== "confirmed_fill") return false;
        if (!isNum(t.realized_pnl_usd)) return false;
        if (assetClass && t.asset_class !== assetClass) return false;
        const ts = toDate(t.timestamp_utc);
        if (!ts) return false;
        return ts.getTime() >= startMs && ts.getTime() <= endMs;
      })
      .sort((a, b) => new Date(a.timestamp_utc) - new Date(b.timestamp_utc));
  }

  /*
   * Baseline for a window, mirroring site_data.py's summarize_period():
   * the last known equity at or before the window start (carried
   * forward), falling back to the first sample inside the window; then
   * re-anchored to the last equity before the earliest trade currently
   * on record if that's newer, which is how a same-day relaunch is
   * handled server-side. Keeping this identical is what stops the chart
   * from disagreeing with the dashboard's Starting Value tile.
   */
  function computeBaseline(startMs) {
    const pts = equityPoints();
    if (!pts.length) return null;
    let base = null;
    const prior = pts.filter((p) => new Date(p.timestamp_utc).getTime() <= startMs);
    if (prior.length) {
      base = { value: prior[prior.length - 1].portfolio_value_usd, ts: prior[prior.length - 1].timestamp_utc };
    } else {
      const inside = pts.filter((p) => new Date(p.timestamp_utc).getTime() >= startMs);
      if (!inside.length) return null;
      base = { value: inside[0].portfolio_value_usd, ts: inside[0].timestamp_utc, isFirstAvailable: true };
    }
    if (trades && trades.available && trades.trades.length) {
      const stamps = trades.trades.map((t) => toDate(t.timestamp_utc)).filter(Boolean).map((d) => d.getTime());
      if (stamps.length) {
        const earliest = Math.min(...stamps);
        if (earliest > new Date(base.ts).getTime()) {
          const before = pts.filter((p) => new Date(p.timestamp_utc).getTime() <= earliest);
          if (before.length) {
            const row = before[before.length - 1];
            if (new Date(row.timestamp_utc).getTime() > new Date(base.ts).getTime()) {
              base = { value: row.portfolio_value_usd, ts: row.timestamp_utc, reanchored: true };
            }
          }
        }
      }
    }
    return base;
  }

  // ---------------------------------------------------------------------
  // Custom HTML tooltip. Chart.js's `external` handler writes into one
  // shared div so styling is fully ours (no default bright theme), and
  // it never flickers because it's only hidden when Chart.js reports
  // opacity 0 AND the tooltip isn't locked open by a tap.
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
      // Every visible series, labeled - hidden (legend-toggled) ones skipped.
      (meta.series || []).forEach((s, di) => {
        if (!ctx.chart.isDatasetVisible(di)) return;
        const rec = s.records[idx];
        html += `<div class="tt-series"><div class="tt-name"><span class="tt-swatch" style="background:${s.color}"></span>${s.label}</div>`;
        if (!rec || !isNum(rec.value)) {
          html += `<div class="tt-row"><span class="tt-label">Value</span><span class="tt-val muted">No recorded value</span></div>`;
        } else {
          const fmtV = s.isPct ? fmtPctSigned : fmtUsdSigned;
          if (isNum(rec.portfolio)) {
            html += `<div class="tt-row"><span class="tt-label">Portfolio value</span><span class="tt-val">${fmtUsd(rec.portfolio)}</span></div>`;
          }
          html += `<div class="tt-row"><span class="tt-label">${s.valueLabel}</span><span class="tt-val ${rec.value >= 0 ? "positive" : "negative"}">${fmtV(rec.value)}</span></div>`;
          if (isNum(rec.pct) && !s.isPct) {
            html += `<div class="tt-row"><span class="tt-label">${s.pctLabel || "Period return"}</span><span class="tt-val ${rec.pct >= 0 ? "positive" : "negative"}">${fmtPctSigned(rec.pct)}</span></div>`;
          }
          if (isNum(rec.delta)) {
            html += `<div class="tt-row"><span class="tt-label">Change</span><span class="tt-val ${rec.delta >= 0 ? "positive" : "negative"}">${fmtV(rec.delta)}</span></div>`;
          } else {
            html += `<div class="tt-row"><span class="tt-label">Change</span><span class="tt-val muted">First sample in range</span></div>`;
          }
        }
        html += `</div>`;
      });
      html += `</div>`;
    } else {
      // Bar / categorical charts.
      html += `<div class="tt-title">${model.title && model.title.length ? model.title[0] : (meta.title || "")}</div>`;
      if (meta.subtitle) html += `<div class="tt-time">${meta.subtitle}</div>`;
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

    // Position next to the cursor, clamped inside the viewport so the
    // tooltip can never run off-screen on a phone.
    const rect = ctx.chart.canvas.getBoundingClientRect();
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let left = rect.left + model.caretX + 14;
    let top = rect.top + model.caretY - h / 2;
    if (left + w > window.innerWidth - 8) left = rect.left + model.caretX - w - 14;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    if (top + h > window.innerHeight - 8) top = window.innerHeight - h - 8;
    el.style.left = left + "px";
    el.style.top = top + "px";
  }

  // Vertical crosshair aligned to the active (snapped) sample, plus the
  // drag-to-zoom selection band. Drawn under the dataset line.
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
      // index+nearest without intersect => hovering anywhere in the plot
      // snaps to the closest real sample; it never interpolates.
      interaction: { mode: "index", intersect: false, axis: "x" },
      plugins: {
        legend: {
          display: (meta.series || []).length > 1 || meta.forceLegend === true,
          position: "top",
          align: "start",
          labels: {
            color: COLORS.text,
            usePointStyle: true,
            pointStyle: "rectRounded",
            boxWidth: 10,
            boxHeight: 10,
            padding: 14,
            font: { size: 11 },
          },
        },
        tooltip: { enabled: false, external: externalTooltip },
      },
      scales: {
        x: {
          ticks: {
            color: COLORS.text,
            maxTicksLimit: meta.maxXTicks || 6,
            autoSkip: true,
            maxRotation: 0,
            minRotation: 0,
            font: { size: 10 },
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
          ticks: {
            color: COLORS.text,
            font: { size: 10 },
            maxTicksLimit: 6,
            callback: meta.yTick || fmtUsdAxis,
          },
          grid: { color: COLORS.grid, drawTicks: false },
          border: { display: false },
        },
      },
    }, extra || {});
  }

  function destroyChart(key) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
  }

  function setEmpty(chartId, message) {
    const wrap = document.getElementById(chartId + "-wrap");
    const empty = document.getElementById(chartId + "-empty");
    const isEmpty = message !== null;
    if (wrap) wrap.hidden = isEmpty;
    if (empty) {
      empty.hidden = !isEmpty;
      if (isEmpty) empty.innerHTML = message;
    }
  }
  function setSummary(chartId, text) {
    const el = document.getElementById(chartId + "-summary");
    if (el) el.textContent = text || "";
  }
  /*
   * "Today" is an ET calendar day, so in the hours just after ET
   * midnight it can legitimately contain zero samples while plenty of
   * recent data exists. Saying only "no data" there is technically true
   * but useless - these point at the most recent real sample instead.
   */
  function lastRecordedIso() {
    const pts = equityPoints();
    return pts.length ? pts[pts.length - 1].timestamp_utc : null;
  }
  function lastSampleNote() {
    const iso = lastRecordedIso();
    if (!iso) return "";
    return `<p>Most recent recorded sample: ${fmtDateTimeET(iso)}. Try a wider range above.</p>`;
  }
  function lastSampleText() {
    const iso = lastRecordedIso();
    return iso ? ` Most recent recorded sample was ${fmtDateTimeET(iso)}.` : "";
  }

  function unrealizedNote(assetClass) {
    const p = dashboard.periods.today;
    const v = assetClass ? (p.unrealized_pnl_by_asset_class || {})[assetClass] : p.unrealized_pnl_usd;
    if (!isNum(v)) return "";
    return `<p class="chart-empty-note ${v >= 0 ? "positive" : "negative"}">Live unrealized P&amp;L on open positions: ${fmtUsdSigned(v)}</p>`;
  }

  // ---------------------------------------------------------------------
  // Main account chart. Combined = whole-account gain/loss vs the
  // range's baseline (with the real portfolio value carried in the
  // tooltip). Stocks/Crypto = cumulative realized P&L from that class's
  // confirmed sells - see the file header for why a per-class portfolio
  // value series does not exist and is not fabricated.
  // ---------------------------------------------------------------------
  function buildEquityModel() {
    const { startMs, endMs, label } = rangeBounds();
    const baseline = computeBaseline(startMs);
    const pts = equityPoints().filter((p) => {
      const d = toDate(p.timestamp_utc);
      return d && d.getTime() >= startMs && d.getTime() <= endMs;
    });

    const wantCombined = category === "combined";
    const wantStock = category === "combined" || category === "stock";
    const wantCrypto = category === "combined" || category === "crypto";

    const stockSells = wantStock ? confirmedSells("stock", startMs, endMs) : [];
    const cryptoSells = wantCrypto ? confirmedSells("crypto", startMs, endMs) : [];

    // Shared, sorted list of REAL sample timestamps only.
    const stampSet = new Set();
    if (wantCombined) pts.forEach((p) => stampSet.add(p.timestamp_utc));
    stockSells.forEach((t) => stampSet.add(t.timestamp_utc));
    cryptoSells.forEach((t) => stampSet.add(t.timestamp_utc));
    const stamps = Array.from(stampSet).sort((a, b) => new Date(a) - new Date(b));
    if (!stamps.length) return { stamps: [], series: [], label, baseline };

    const series = [];

    if (wantCombined && baseline && pts.length) {
      const byStamp = new Map(pts.map((p) => [p.timestamp_utc, p]));
      const records = [];
      let prev = null;
      stamps.forEach((s) => {
        const p = byStamp.get(s);
        if (!p) { records.push(null); return; }   // real gap, not zero
        const gain = p.portfolio_value_usd - baseline.value;
        const rec = {
          value: gain,
          portfolio: p.portfolio_value_usd,
          pct: baseline.value ? (p.portfolio_value_usd / baseline.value - 1) * 100 : null,
          delta: prev === null ? null : p.portfolio_value_usd - prev,
        };
        prev = p.portfolio_value_usd;
        records.push(rec);
      });
      series.push({
        key: "combined", label: "Combined Portfolio", color: COLORS.combined,
        valueLabel: "Gain / loss vs. baseline", pctLabel: "Period return", records,
      });
    }

    function classSeries(sells, key, label, color) {
      if (!sells.length) return null;
      const byStamp = new Map();
      let running = 0;
      sells.forEach((t) => {
        running += t.realized_pnl_usd;
        byStamp.set(t.timestamp_utc, { cum: running, trade: t.realized_pnl_usd });
      });
      const records = [];
      let prevCum = null;
      stamps.forEach((s) => {
        const hit = byStamp.get(s);
        if (!hit) { records.push(null); return; }
        records.push({
          value: hit.cum,
          portfolio: null,
          pct: baseline && baseline.value ? (hit.cum / baseline.value) * 100 : null,
          delta: prevCum === null ? null : hit.cum - prevCum,
        });
        prevCum = hit.cum;
      });
      // Deliberately NOT called a "return": this is realized P&L measured
      // against the whole account's baseline, not that asset class's own
      // invested capital (which the logs don't record historically).
      return { key, label, color, valueLabel: "Cumulative realized P&L", pctLabel: "% of account baseline", records };
    }

    const s1 = classSeries(stockSells, "stock", "Stocks (realized)", COLORS.stock);
    if (s1) series.push(s1);
    const s2 = classSeries(cryptoSells, "crypto", "Crypto (realized)", COLORS.crypto);
    if (s2) series.push(s2);

    return { stamps, series, label, baseline };
  }

  function renderEquityChart() {
    const canvas = document.getElementById("chart-equity");
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart("equity");

    const model = buildEquityModel();
    const heading = document.getElementById("equity-heading");
    if (heading) {
      heading.textContent = category === "combined" ? "Account Gain / Loss"
        : category === "stock" ? "Stocks — Cumulative Realized P&L"
        : "Crypto — Cumulative Realized P&L";
    }

    if (!model.series.length) {
      const what = category === "combined" ? "equity history" : `${category === "stock" ? "stock" : "crypto"} sell history`;
      setEmpty("chart-equity", `<p>No ${what} recorded in this range.</p>${lastSampleNote()}${category === "combined" ? "" : unrealizedNote(category)}`);
      setSummary("chart-equity", `No recorded ${what} for ${model.label.toLowerCase()}.${lastSampleText()}`);
      return;
    }
    setEmpty("chart-equity", null);

    const multiDay = new Set(model.stamps.map(etDayKey)).size > 1;
    const meta = {
      kind: "timeseries",
      title: category === "combined" ? "Combined Portfolio" : category === "stock" ? "Stocks" : "Crypto",
      stamps: model.stamps,
      series: model.series,
      multiDay,
      maxXTicks: 7,
      beginAtZero: false,
      yTick: fmtUsdAxis,
      // Always show the legend on the main chart, even with a single
      // series - it names what the line actually is, and stays the
      // click target for toggling series once more than one exists.
      forceLegend: true,
    };

    charts.equity = new Chart(canvas, {
      type: "line",
      data: {
        labels: model.stamps.map((_, i) => i),
        datasets: model.series.map((s) => ({
          label: s.label,
          data: s.records.map((r) => (r ? r.value : null)),
          borderColor: s.color,
          backgroundColor: s.color,
          borderWidth: 2,
          tension: 0.18,          // smooth but restrained
          fill: false,            // no heavy area fills
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBorderWidth: 2,
          pointHoverBorderColor: "#050706",
          spanGaps: false,        // a real gap stays a gap
        })),
      },
      options: baseOptions(meta),
      plugins: [crosshairPlugin],
    });
    charts.equity.$ibMeta = meta;
    if (zoom) {
      charts.equity.options.scales.x.min = zoom.min;
      charts.equity.options.scales.x.max = zoom.max;
      charts.equity.update("none");
    }

    attachInteractions(charts.equity, meta);
    writeEquitySummary(model);
  }

  function writeEquitySummary(model) {
    const parts = [];
    model.series.forEach((s) => {
      // Index-tracked so a series' first/last REAL sample is paired with
      // its own timestamp - never another series' timestamp.
      const realIdx = [];
      s.records.forEach((r, i) => { if (r && isNum(r.value)) realIdx.push(i); });
      if (!realIdx.length) return;
      const first = s.records[realIdx[0]];
      const last = s.records[realIdx[realIdx.length - 1]];
      const firstIso = model.stamps[realIdx[0]];
      const lastIso = model.stamps[realIdx[realIdx.length - 1]];
      const real = realIdx;
      parts.push(
        `${s.label}: ${real.length} recorded sample${real.length === 1 ? "" : "s"} from ${fmtDateTimeET(firstIso)} to ${fmtDateTimeET(lastIso)}, ` +
        `moving from ${fmtUsdSigned(first.value)} to ${fmtUsdSigned(last.value)}` +
        (isNum(last.pct) ? ` (${fmtPctSigned(last.pct)})` : "") + "."
      );
    });
    const base = model.baseline
      ? ` Baseline ${fmtUsd(model.baseline.value)} as of ${fmtDateTimeET(model.baseline.ts)}${model.baseline.reanchored ? " (anchored to the most recent relaunch)" : ""}.`
      : "";
    setSummary("chart-equity", `${model.label}. ` + (parts.join(" ") || "No recorded values.") + base);
  }

  // ---------------------------------------------------------------------
  // Hover / tap / drag-zoom wiring
  // ---------------------------------------------------------------------
  function attachInteractions(chart, meta) {
    const canvas = chart.canvas;

    if (IS_TOUCH) {
      // Lock on touchstart, NOT on click: Chart.js handles touchstart
      // first (populating the tooltip), and the browser's synthetic
      // click/mouseout that follows a tap would otherwise arrive while
      // the tooltip was still unlocked and immediately hide it again -
      // which is exactly why tapping a point appeared to do nothing.
      // Dismissal is handled by the document-level click listener in
      // boot(), which ignores taps that landed on a canvas.
      ["touchstart", "click"].forEach((ev) => {
        canvas.addEventListener(ev, () => { tooltipLocked = true; }, { passive: true });
      });
    } else {
      canvas.addEventListener("mouseleave", () => { if (!tooltipLocked) hideTooltip(); });
    }

    // Drag-to-zoom (desktop only, and only where there's enough history
    // to be worth it). Optional by design: the default view is already
    // correctly scaled and fully readable without ever zooming.
    if (!IS_TOUCH && meta.kind === "timeseries" && (meta.stamps || []).length > 12) {
      chart.$ibDrag = { active: false, fromX: null, toX: null, fromIdx: null };
      const idxAt = (evt) => {
        const rect = canvas.getBoundingClientRect();
        const x = evt.clientX - rect.left;
        const area = chart.chartArea;
        if (!area || x < area.left || x > area.right) return null;
        const scale = chart.scales.x;
        return Math.round(scale.getValueForPixel(x));
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
        if (hi - lo < 2) { chart.draw(); return; }   // ignore stray clicks
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
  // Supporting charts
  // ---------------------------------------------------------------------
  function renderDailyPnl() {
    const canvas = document.getElementById("chart-daily-pnl");
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart("dailyPnl");
    const { startMs, endMs, label } = rangeBounds();
    const pts = equityPoints().filter((p) => {
      const d = toDate(p.timestamp_utc);
      return d && d.getTime() >= startMs && d.getTime() <= endMs;
    });
    // Last recorded equity per ET calendar day, then day-over-day diff.
    const byDay = new Map();
    pts.forEach((p) => { const k = etDayKey(p.timestamp_utc); if (k) byDay.set(k, p); });
    const days = Array.from(byDay.keys()).sort();
    const rows = [];
    for (let i = 1; i < days.length; i++) {
      rows.push({ day: days[i], pnl: byDay.get(days[i]).portfolio_value_usd - byDay.get(days[i - 1]).portfolio_value_usd });
    }
    if (!rows.length) {
      setEmpty("chart-daily-pnl", `<p>Day-over-day P&amp;L needs at least two ET calendar days of equity history. ${days.length === 1 ? `Only one ET day (${days[0]}) is recorded in this range so far.` : "No equity history in this range."}</p>${days.length ? "" : lastSampleNote()}`);
      setSummary("chart-daily-pnl", `No day-over-day P&L available for ${label.toLowerCase()} - it needs at least two recorded ET calendar days${days.length === 1 ? `, and only ${days[0]} is recorded so far` : ""}.`);
      return;
    }
    setEmpty("chart-daily-pnl", null);
    const meta = {
      kind: "bar", title: "Daily P&L", subtitle: null,
      stamps: rows.map((r) => r.day), maxXTicks: 7,
      valueFormatter: fmtUsdSigned,
    };
    charts.dailyPnl = new Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map((r) => new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(r.day + "T00:00:00Z"))),
        datasets: [{
          label: "Daily P&L",
          data: rows.map((r) => r.pnl),
          backgroundColor: rows.map((r) => (r.pnl >= 0 ? COLORS.green : COLORS.red)),
          borderRadius: 3,
        }],
      },
      options: baseOptions({ maxXTicks: 8, yTick: fmtUsdAxis }, {
        scales: {
          x: { ticks: { color: COLORS.text, font: { size: 10 }, maxRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 6, callback: fmtUsdAxis }, grid: { color: COLORS.grid, drawTicks: false }, border: { display: false } },
        },
      }),
      plugins: [crosshairPlugin],
    });
    charts.dailyPnl.$ibMeta = meta;
    const best = rows.reduce((a, b) => (b.pnl > a.pnl ? b : a));
    const worst = rows.reduce((a, b) => (b.pnl < a.pnl ? b : a));
    setSummary("chart-daily-pnl", `${label}: ${rows.length} full day${rows.length === 1 ? "" : "s"} of day-over-day change. Best ${fmtUsdSigned(best.pnl)} on ${best.day}; worst ${fmtUsdSigned(worst.pnl)} on ${worst.day}.`);
  }

  function renderDrawdown() {
    const canvas = document.getElementById("chart-drawdown");
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart("drawdown");
    const { startMs, endMs, label } = rangeBounds();
    const pts = equityPoints().filter((p) => {
      const d = toDate(p.timestamp_utc);
      return d && d.getTime() >= startMs && d.getTime() <= endMs;
    });
    if (pts.length < 2) {
      setEmpty("chart-drawdown", `<p>Not enough equity history in this range to measure drawdown (needs at least two recorded samples; this range has ${pts.length}).</p>${lastSampleNote()}`);
      setSummary("chart-drawdown", `Not enough recorded equity history for ${label.toLowerCase()} to measure drawdown.${lastSampleText()}`);
      return;
    }
    setEmpty("chart-drawdown", null);
    // Running peak-to-current decline. Each record keeps the real
    // portfolio value it was derived from so the tooltip's timestamp,
    // equity and drawdown all come from one and the same sample.
    let peak = pts[0].portfolio_value_usd;
    let prevDd = null;
    const records = pts.map((p) => {
      peak = Math.max(peak, p.portfolio_value_usd);
      const dd = peak > 0 ? ((p.portfolio_value_usd - peak) / peak) * 100 : 0;
      const rec = { value: dd, portfolio: p.portfolio_value_usd, pct: null, delta: prevDd === null ? null : dd - prevDd, peak };
      prevDd = dd;
      return rec;
    });
    const stamps = pts.map((p) => p.timestamp_utc);
    const multiDay = new Set(stamps.map(etDayKey)).size > 1;
    const meta = {
      kind: "timeseries", title: "Drawdown From Peak", stamps, multiDay,
      // Deliberately few ticks: this card is narrow and long ET
      // timestamps stack up illegibly otherwise.
      maxXTicks: 4, beginAtZero: false, yTick: fmtPctAxis,
      series: [{
        key: "dd", label: "Drawdown from peak", color: COLORS.red,
        valueLabel: "Drawdown", isPct: true, records,
      }],
    };
    charts.drawdown = new Chart(canvas, {
      type: "line",
      data: {
        labels: stamps.map((_, i) => i),
        datasets: [{
          label: "Drawdown (%)",
          data: records.map((r) => r.value),
          borderColor: COLORS.red,
          backgroundColor: "rgba(240,85,74,0.08)",
          borderWidth: 2,
          tension: 0.18,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          spanGaps: false,
        }],
      },
      options: baseOptions(meta),
      plugins: [crosshairPlugin],
    });
    charts.drawdown.$ibMeta = meta;
    const trough = records.reduce((a, b) => (b.value < a.value ? b : a));
    const troughIso = stamps[records.indexOf(trough)];
    setSummary("chart-drawdown", `${label}: ${records.length} recorded samples. Deepest drawdown ${fmtPctSigned(trough.value)} at ${fmtDateTimeET(troughIso)}. Current ${fmtPctSigned(records[records.length - 1].value)}.`);
  }

  function renderStrategy() {
    const canvas = document.getElementById("chart-strategy");
    if (typeof Chart === "undefined" || !canvas) return;
    destroyChart("strategy");
    const { startMs, endMs, label } = rangeBounds();
    const cls = category === "combined" ? null : category;
    const sells = confirmedSells(cls, startMs, endMs);
    if (!sells.length) {
      setEmpty("chart-strategy", `<p>No closed trades yet in this range${cls ? ` for ${cls === "stock" ? "stocks" : "crypto"}` : ""}, so there's no realized P&amp;L to compare by strategy.</p>${unrealizedNote(cls)}`);
      setSummary("chart-strategy", `No confirmed sell trades recorded for ${label.toLowerCase()}${cls ? ` in ${cls === "stock" ? "stocks" : "crypto"}` : ""}, so no realized P&L by strategy is available.`);
      return;
    }
    setEmpty("chart-strategy", null);
    const byStrategy = new Map();
    sells.forEach((t) => {
      const k = t.strategy || "unknown";
      byStrategy.set(k, (byStrategy.get(k) || 0) + t.realized_pnl_usd);
    });
    const keys = Array.from(byStrategy.keys()).sort();
    charts.strategy = new Chart(canvas, {
      type: "bar",
      data: {
        labels: keys,
        datasets: [{
          label: "Realized P&L",
          data: keys.map((k) => byStrategy.get(k)),
          backgroundColor: keys.map((k) => (byStrategy.get(k) >= 0 ? COLORS.green : COLORS.red)),
          borderRadius: 3,
        }],
      },
      options: baseOptions({ maxXTicks: 8, yTick: fmtUsdAxis }, {
        scales: {
          x: { ticks: { color: COLORS.text, font: { size: 10 }, maxRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, ticks: { color: COLORS.text, font: { size: 10 }, maxTicksLimit: 6, callback: fmtUsdAxis }, grid: { color: COLORS.grid, drawTicks: false }, border: { display: false } },
        },
      }),
      plugins: [crosshairPlugin],
    });
    charts.strategy.$ibMeta = { kind: "bar", title: "Realized P&L by strategy", valueFormatter: fmtUsdSigned };
    setSummary("chart-strategy", `${label}: ${sells.length} confirmed sell${sells.length === 1 ? "" : "s"} across ${keys.length} strateg${keys.length === 1 ? "y" : "ies"} — ` +
      keys.map((k) => `${k} ${fmtUsdSigned(byStrategy.get(k))}`).join(", ") + ".");
  }

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
    let running = 0;
    const stamps = [];
    const records = [];
    let prev = null;
    sells.forEach((t) => {
      running += t.realized_pnl_usd;
      stamps.push(t.timestamp_utc);
      records.push({ value: running, portfolio: null, pct: null, delta: prev === null ? null : running - prev, trade: t });
      prev = running;
    });
    const multiDay = new Set(stamps.map(etDayKey)).size > 1;
    const meta = {
      kind: "timeseries",
      title: assetClass === "stock" ? "Stocks — cumulative realized P&L" : "Crypto — cumulative realized P&L",
      stamps, multiDay, maxXTicks: 5, beginAtZero: true, yTick: fmtUsdAxis,
      series: [{ key: assetClass, label: `${assetClass === "stock" ? "Stocks" : "Crypto"} (realized)`, color, valueLabel: "Cumulative realized P&L", records }],
    };
    // Each point also carries the individual fill that moved the line.
    records.forEach((r, i) => { r.tradeNote = `${sells[i].ticker} ${fmtUsdSigned(sells[i].realized_pnl_usd)}`; });
    charts[chartKey] = new Chart(canvas, {
      type: "line",
      data: {
        labels: stamps.map((_, i) => i),
        datasets: [{
          label: `${assetClass === "stock" ? "Stocks" : "Crypto"} realized P&L`,
          data: records.map((r) => r.value),
          borderColor: color,
          backgroundColor: color,
          borderWidth: 2,
          stepped: "after",   // realized P&L only moves when a sell fills
          fill: false,
          pointRadius: 3,
          pointHoverRadius: 6,
          spanGaps: false,
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
      data: {
        labels: tickers,
        datasets: [
          { label: "Wins", data: wins, backgroundColor: COLORS.green, borderRadius: 3 },
          { label: "Losses", data: losses, backgroundColor: COLORS.red, borderRadius: 3 },
        ],
      },
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
  // Orchestration
  // ---------------------------------------------------------------------
  function renderAll() {
    hideTooltip();
    tooltipLocked = false;
    renderEquityChart();
    renderDailyPnl();
    renderDrawdown();
    renderStrategy();
    renderClassCumPnl("crypto", "chart-crypto-cum-pnl", "cryptoCumPnl", COLORS.crypto);
    renderClassWinLoss("crypto", "chart-crypto-winloss", "cryptoWinLoss");
    renderClassCumPnl("stock", "chart-stock-cum-pnl", "stockCumPnl", COLORS.stock);
    renderClassWinLoss("stock", "chart-stock-winloss", "stockWinLoss");

    // The per-class sections are redundant when you've already filtered
    // the whole page to one class.
    const cs = document.getElementById("section-crypto");
    const ss = document.getElementById("section-stocks");
    if (cs) cs.hidden = category === "stock";
    if (ss) ss.hidden = category === "crypto";

    syncZoomUi();
  }

  function boot() {
    // Controls are wired first and unconditionally so they always
    // respond even if a later render throws on unexpected data.
    document.querySelectorAll("#range-control button").forEach((btn) => {
      btn.addEventListener("click", () => {
        rangeKey = btn.dataset.range;
        zoom = null;
        document.querySelectorAll("#range-control button").forEach((b) => b.classList.toggle("active", b === btn));
        safely("range change", renderAll);
      });
    });
    document.querySelectorAll("#category-control button").forEach((btn) => {
      btn.addEventListener("click", () => {
        category = btn.dataset.category;
        zoom = null;
        document.querySelectorAll("#category-control button").forEach((b) => b.classList.toggle("active", b === btn));
        safely("category change", renderAll);
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
    // Tapping anywhere off a canvas dismisses a locked tooltip.
    document.addEventListener("click", (e) => {
      if (tooltipLocked && e.target.tagName !== "CANVAS") {
        tooltipLocked = false;
        hideTooltip();
      }
    });
    window.addEventListener("resize", () => { hideTooltip(); tooltipLocked = false; });

    load();
  }

  function safely(label, fn) {
    try { fn(); } catch (err) { console.error(`[investingbot] ${label} failed:`, err); }
  }

  async function load() {
    [dashboard, trades, equity] = await Promise.all([
      loadJson("dashboard.json", null),
      loadJson("trades.json", { available: false, trades: [] }),
      loadJson("equity.json", { available: false, points: [] }),
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
        "Note on the Stocks/Crypto split: the stock and crypto workflows each log the whole account's value, " +
        "not a separate per-asset-class balance, so a historical portfolio value split by asset class doesn't exist in the logs " +
        "and isn't estimated here. The per-class series show cumulative realized P&L from confirmed sell fills, which is genuinely per-class and timestamped.";
    }

    safely("charts", renderAll);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
