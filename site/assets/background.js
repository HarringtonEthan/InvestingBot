/*
 * Purely decorative ambient background - a single canvas drawing a
 * sparse field of slowly-drifting particles with faint connecting
 * lines, an occasional subtle rising/falling "ghost" market-line path,
 * and a small cursor-eased parallax on desktop. None of this reads any
 * page data or touches the dashboard's own DOM/state - it draws to its
 * own canvas and nothing else.
 *
 * Respects the same constraints the rest of this site already holds
 * itself to: never blocks clicks/selection (pointer-events:none, set in
 * CSS), pauses entirely under prefers-reduced-motion (draws exactly one
 * static frame, never schedules another), pauses while the tab isn't
 * visible, and scales itself down on narrow/mobile viewports instead of
 * assuming desktop-class hardware.
 */

(function () {
  "use strict";

  const canvas = document.getElementById("bg-canvas");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const IS_NARROW = window.matchMedia("(max-width: 700px)").matches;
  const IS_TOUCH = window.matchMedia("(hover: none)").matches;

  // Calm, restrained palette - the brand green plus a few cool accents,
  // red kept rare so it never reads as an alert or a loss signal (this
  // layer carries no meaning, unlike the red used elsewhere on the page
  // for real negative numbers).
  const COLORS = ["52,211,114", "106,166,255", "56,189,214", "154,124,224"];
  const RARE_COLOR = "224,110,102";
  const RARE_CHANCE = 0.05;

  let width = 0, height = 0;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // Sparse by design - this is atmosphere, not a feature. Fewer, smaller
  // particles on narrow/mobile viewports where CPUs are typically
  // weaker and screen space is more precious.
  function targetCount() {
    const byArea = Math.round((width * height) / 24000);
    return Math.max(12, Math.min(byArea, IS_NARROW ? 22 : 60));
  }

  let particles = [];
  function makeParticles() {
    const n = targetCount();
    particles = [];
    for (let i = 0; i < n; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.09,
        vy: (Math.random() - 0.5) * 0.09,
        r: 1 + Math.random() * 1.3,
        color: Math.random() < RARE_CHANCE ? RARE_COLOR : COLORS[(Math.random() * COLORS.length) | 0],
        alpha: 0.22 + Math.random() * 0.3,
      });
    }
  }

  const LINK_DIST = IS_NARROW ? 85 : 125;

  // A single faint "ghost" market-line drifts across the middle band of
  // the screen every so often, fades in and back out, then is gone for
  // a long while - occasional, not a recurring ticker.
  let ghostLine = null;
  function maybeSpawnGhostLine(now) {
    if (ghostLine || Math.random() > 0.0012) return;
    const segs = 22;
    const points = [];
    let y = height * (0.28 + Math.random() * 0.44);
    for (let i = 0; i <= segs; i++) {
      y += (Math.random() - 0.5) * height * 0.035;
      y = Math.max(height * 0.12, Math.min(height * 0.88, y));
      points.push(y);
    }
    ghostLine = {
      points,
      born: now,
      lifespan: 11000 + Math.random() * 6000,
      color: Math.random() < 0.65 ? COLORS[0] : COLORS[1],
    };
  }

  function drawGhostLine(now) {
    if (!ghostLine) return;
    const age = now - ghostLine.born;
    const t = age / ghostLine.lifespan;
    if (t >= 1) { ghostLine = null; return; }
    // Reveal left-to-right over the first 40% of its life, hold, then
    // fade out over the last 35% - never a hard cut, always eased.
    const reveal = Math.min(1, t / 0.4);
    const fade = t < 0.65 ? 1 : Math.max(0, 1 - (t - 0.65) / 0.35);
    if (fade <= 0.01) { ghostLine = null; return; }
    const pts = ghostLine.points;
    const segW = width / (pts.length - 1);
    const visible = Math.max(2, Math.floor(pts.length * reveal));
    ctx.beginPath();
    ctx.strokeStyle = `rgba(${ghostLine.color},${(0.09 * fade).toFixed(3)})`;
    ctx.lineWidth = 1.3;
    for (let i = 0; i < visible; i++) {
      const x = i * segW;
      const y = pts[i];
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Cursor parallax: the target updates instantly on mousemove, but the
  // applied offset eases toward it slowly, so the scene drifts gently
  // with pointer position instead of snapping to it. Desktop/hover-
  // capable devices only - nothing to parallax against on a touchscreen.
  let targetX = 0, targetY = 0, offsetX = 0, offsetY = 0;
  if (!IS_TOUCH && !REDUCED_MOTION) {
    window.addEventListener("mousemove", (e) => {
      targetX = (e.clientX / width - 0.5) * 2;
      targetY = (e.clientY / height - 0.5) * 2;
    }, { passive: true });
  }

  // Scroll parallax: the backdrop drifts vertically at a fraction of
  // the page's own scroll speed, so it reads as sitting a bit further
  // back than the content scrolling past it rather than pinned flat to
  // the viewport. Unlike the cursor parallax above, this applies on
  // touch devices too - scrolling has nothing to do with pointer
  // capability. Capped so an unusually long page (charts.html) never
  // drifts the backdrop further than a small, still-subtle distance.
  let targetScrollY = 0, scrollOffsetY = 0;
  if (!REDUCED_MOTION) {
    window.addEventListener("scroll", () => {
      targetScrollY = Math.max(-140, Math.min(140, window.scrollY * -0.04));
    }, { passive: true });
  }

  let rafId = null;

  function step(now) {
    ctx.clearRect(0, 0, width, height);

    offsetX += (targetX - offsetX) * 0.035;
    offsetY += (targetY - offsetY) * 0.035;
    scrollOffsetY += (targetScrollY - scrollOffsetY) * 0.06;

    ctx.save();
    ctx.translate(offsetX * 9, offsetY * 7 + scrollOffsetY);

    if (!REDUCED_MOTION) {
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < -20) p.x = width + 20; else if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20; else if (p.y > height + 20) p.y = -20;
      }
    }

    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const a = particles[i], b = particles[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < LINK_DIST) {
          ctx.strokeStyle = `rgba(${a.color},${((1 - dist / LINK_DIST) * 0.06).toFixed(3)})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }

    for (const p of particles) {
      ctx.beginPath();
      ctx.fillStyle = `rgba(${p.color},${p.alpha.toFixed(3)})`;
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }

    if (!REDUCED_MOTION) {
      maybeSpawnGhostLine(now);
      drawGhostLine(now);
    }

    ctx.restore();

    // Under reduced motion this single call never reschedules itself -
    // exactly one static frame is drawn and the canvas then sits still.
    if (!REDUCED_MOTION) {
      rafId = requestAnimationFrame(step);
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
    } else if (!REDUCED_MOTION && rafId === null) {
      rafId = requestAnimationFrame(step);
    }
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      resize();
      makeParticles();
    }, 200);
  }, { passive: true });

  resize();
  makeParticles();
  step(performance.now());
})();
