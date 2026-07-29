/*
 * Pure decoration: the panda-kiss intro splash - the one deliberately
 * playful thing left on the site. Never reads dashboard.json/
 * positions.json/trades.json/equity.json or touches any real number.
 */

(function () {
  "use strict";

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  document.addEventListener("DOMContentLoaded", initPandaIntro);
})();
