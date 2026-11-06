/* The Silver/Bronze banner on the PV Atlas pages can be closed (owner, 2026-11-06).
 *
 * scripts/build_atlas_pages.py writes the banner with a hidden close button; this shows
 * the button and remembers a closed banner in this browser, keyed by the banner's own
 * text: a banner with the same wording stays closed on every page that carries it, and
 * a reworded one (another country's, or a new message) shows again. Storage can be
 * missing or refuse writes (private windows, blocked site data), so every access is
 * guarded and the banner then simply closes for this visit only.
 */
(function () {
  "use strict";

  var PREFIX = "earthpv-tier-banner:";

  // A short, stable fingerprint of the banner's wording (djb2 over its text).
  function keyOf(banner) {
    var text = (banner.textContent || "").replace(/\s+/g, " ").trim();
    var h = 5381;
    for (var i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
    return PREFIX + (h >>> 0).toString(36);
  }

  function closed(key) {
    try {
      return window.localStorage.getItem(key) === "closed";
    } catch (err) {
      return false;
    }
  }

  function remember(key) {
    try {
      window.localStorage.setItem(key, "closed");
    } catch (err) {
      /* closes for this visit only */
    }
  }

  function attach() {
    var banners = document.querySelectorAll(".atlas-tier-alert");
    for (var i = 0; i < banners.length; i++) {
      var banner = banners[i];
      var button = banner.querySelector(".atlas-tier-close");
      if (!button || button.dataset.pvBound) continue;
      var key = keyOf(banner);
      if (closed(key)) {
        banner.hidden = true;
        continue;
      }
      button.dataset.pvBound = "1";
      button.hidden = false;
      button.addEventListener("click", function (b, k) {
        return function () {
          b.hidden = true;
          remember(k);
        };
      }(banner, key));
    }
  }

  // Same per-page hook as embed-theme.js: Material's `document$`, else the DOM.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(attach);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attach);
  } else {
    attach();
  }
})();
