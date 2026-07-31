// Light/dark theme switching.
//
// This file is loaded early in <head> - before body content paints - so
// the correct data-theme attribute is stamped onto <html> before the
// browser renders a single pixel. That avoids a flash of the wrong
// theme (e.g. a light-mode user briefly seeing the dark default while
// the rest of the page's scripts load).
//
// Preference order: an explicit choice the user already made this
// session (localStorage) beats the OS-level prefers-color-scheme,
// which beats the site's own dark-by-default.
(function () {
  const STORAGE_KEY = "ib-theme";

  function systemPrefersLight() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  }

  function getStoredTheme() {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      return null;
    }
  }

  function resolveInitialTheme() {
    const stored = getStoredTheme();
    if (stored === "light" || stored === "dark") return stored;
    return systemPrefersLight() ? "light" : "dark";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  // Runs immediately (this script is loaded synchronously in <head>,
  // before <body>), not on any DOMContentLoaded/load event.
  applyTheme(resolveInitialTheme());

  window.ibTheme = {
    get() {
      return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    },
    toggle() {
      const next = window.ibTheme.get() === "light" ? "dark" : "light";
      applyTheme(next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch (err) {
        // Private-browsing/storage-disabled: theme still applies for
        // this page view, it just won't persist across visits.
      }
      document.dispatchEvent(new CustomEvent("ib:theme-changed", { detail: { theme: next } }));
    },
  };
})();
