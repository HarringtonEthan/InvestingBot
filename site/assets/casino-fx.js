/*
 * Pure decoration: fireworks, the ambient "Family" blackjack lounge, and
 * the panda-kiss intro splash. Deliberately its own file, separate from
 * dashboard.js - nothing in here ever reads dashboard.json/positions.json/
 * trades.json/equity.json or touches any real number on the page.
 */

(function () {
  "use strict";

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FIREWORK_COLORS = ["#ffd700", "#39ff14", "#ff2fb0", "#a259ff", "#ff3b3b", "#00e5ff"];
  const MOBSTERS = [
    { face: "🐻", drink: "🥃" },
    { face: "🦁", drink: "🍸" },
    { face: "🐯", drink: "🥃" },
    { face: "🐺", drink: "🍷" },
    { face: "🦊", drink: "🍹" },
  ];

  function buildFireworks() {
    if (REDUCED_MOTION) return; // layer is display:none via CSS anyway
    const layer = document.createElement("div");
    layer.className = "fireworks-layer";
    layer.setAttribute("aria-hidden", "true");
    const count = 7;
    for (let i = 0; i < count; i++) {
      const fw = document.createElement("div");
      fw.className = "firework";
      fw.style.left = 8 + Math.random() * 84 + "%";
      fw.style.top = 5 + Math.random() * 55 + "%";
      fw.style.color = FIREWORK_COLORS[i % FIREWORK_COLORS.length];
      fw.style.animationDelay = -(Math.random() * 3.4) + "s";
      layer.appendChild(fw);
    }
    document.body.prepend(layer);
  }

  function buildMobScene() {
    const container = document.getElementById("mob-scene-root");
    if (!container) return;
    const strip = document.createElement("div");
    strip.className = "mob-table-strip";
    MOBSTERS.forEach((m) => {
      const el = document.createElement("div");
      el.className = "mobster";
      el.innerHTML = `
        <div class="mobster-hat">🎩</div>
        <div class="mobster-face">${m.face}</div>
        <div class="mobster-suit"></div>
        <div class="mobster-props">
          <span class="mobster-drink">${m.drink}</span>
          <span class="mobster-cigar">🚬<span class="smoke"></span><span class="smoke"></span><span class="smoke"></span></span>
        </div>`;
      strip.appendChild(el);
    });
    const waiter = document.createElement("div");
    waiter.className = "waiter";
    waiter.innerHTML = "🤵<span class=\"tray\">🍸</span>";
    container.appendChild(strip);
    container.appendChild(waiter);
  }

  function initPandaIntro() {
    const el = document.getElementById("panda-intro");
    if (!el) return;
    const dismiss = () => {
      el.style.display = "none";
    };
    if (REDUCED_MOTION) {
      dismiss();
      return;
    }
    el.addEventListener("click", dismiss);
    // Matches the CSS panda-intro-fade animation length (3.2s) - removes
    // it from the DOM afterward so it can never sit invisibly on top of
    // (and block clicks on) the real dashboard underneath.
    setTimeout(dismiss, 3300);
  }

  document.addEventListener("DOMContentLoaded", () => {
    buildFireworks();
    buildMobScene();
    initPandaIntro();
  });
})();
