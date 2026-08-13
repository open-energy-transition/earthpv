/* Keep the embedded interactive pages on the same theme as the site.
 *
 * The result pages (`src/earthpv/templates/pv_evidence_atlas.html`,
 * `pv_growth_atlas.html`, `src/earthpv/pose.py`) are standalone documents with no
 * light/dark switch of their own: they read `data-theme` off their own <html>, falling
 * back to `prefers-color-scheme`. Material's switch is separate and writes
 * `data-md-color-scheme` on <body>. Left alone, the two disagree the moment a reader
 * uses the site toggle without also changing the operating system preference -- a dark
 * page with a cream atlas glued into the middle of it.
 *
 * They are served from the same origin (docs/assets/interactive/), so this reaches into
 * each frame and sets `data-theme` directly. The evidence atlas and the pose page
 * observe that attribute themselves (a MutationObserver re-renders the SVG on change);
 * `pv_growth_atlas.html` still drives its recolour off a `#themeBtn` click handler, so
 * for that page only, `syncFrame` clicks the button instead of setting the attribute.
 */
(function () {
  "use strict";

  function siteWantsDark() {
    var scheme = document.body.getAttribute("data-md-color-scheme");
    if (scheme) return scheme === "slate";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function syncFrame(frame) {
    var doc;
    try {
      doc = frame.contentDocument;
    } catch (err) {
      return; // cross-origin, not one of ours
    }
    if (!doc || !doc.documentElement) return;

    var root = doc.documentElement;
    var pinned = root.getAttribute("data-theme");
    var want = siteWantsDark() ? "dark" : "light";

    // The frame's scrollbar is drawn by the browser, not by the page's CSS, so a page
    // that paints itself dark still gets a light scrollbar down the side of the panel.
    // The templates declare both of these; pages built before they did do not, and the
    // docs site copies whatever artifact is on disk, so set them here too. Measured in
    // Firefox 2026-08: `color-scheme` alone computes correctly on the frame's root and
    // still leaves the scrollbar light, so `scrollbar-color` is the one doing the work
    // -- keep both, since color-scheme is what form controls and the canvas read.
    root.style.colorScheme = want;
    root.style.scrollbarColor =
      want === "dark" ? "#4a3a1c #14100b" : "#c3b492 #ece4d2";
    // Same fallback the embedded pages use, evaluated in their own frame.
    var current =
      pinned ||
      (frame.contentWindow.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light");

    if (current === want) {
      // Already correct, but unpinned: pin it so a later OS change cannot desync the
      // frame from the site while the site stays on an explicit choice.
      if (!pinned) root.setAttribute("data-theme", want);
      return;
    }

    var btn = doc.getElementById("themeBtn");
    if (btn) btn.click();
    else root.setAttribute("data-theme", want); // page without a toggle of its own
  }

  function syncAll() {
    var frames = document.querySelectorAll(".embed iframe");
    for (var i = 0; i < frames.length; i++) syncFrame(frames[i]);
  }

  function attach() {
    var frames = document.querySelectorAll(".embed iframe");
    for (var i = 0; i < frames.length; i++) {
      var frame = frames[i];
      if (!frame.dataset.pvThemeBound) {
        frame.dataset.pvThemeBound = "1";
        frame.addEventListener("load", syncFrame.bind(null, frame));
      }
      syncFrame(frame); // already loaded from cache, or a no-op before load
    }

    // Material rewrites the attribute in place when the palette toggle is used. <body>
    // survives instant navigation, so bind the observer once rather than per page.
    if (!document.body.dataset.pvThemeObserved) {
      document.body.dataset.pvThemeObserved = "1";
      new MutationObserver(syncAll).observe(document.body, {
        attributes: true,
        attributeFilter: ["data-md-color-scheme"],
      });
    }
  }

  // `document$` is Material's per-page-load subject; it also fires once without
  // instant navigation, and guarding on it keeps this working if that feature is
  // switched on later.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(attach);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", attach);
  } else {
    attach();
  }
})();
