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

  // An embed marked `.embed.fit` is sized to its own content instead of scrolling inside
  // the fixed 760 px box, for a page whose 3D view zooms on scroll and would otherwise
  // fight the frame's own scrolling (PVscope). The PV Atlas pages (`.page-full-bleed.fit`,
  // scripts/build_atlas_pages.py) are sized the same way, so the site page scrolls as one
  // and the switcher and tier banner scroll away above the map. It measures <body>, not
  // scrollHeight: scrollHeight never drops below the frame's current height, so a frame
  // sized that way can grow but never shrink back after the reader widens the window.
  // A map put in fullscreen leaves its page's flow, so <body> shrinks by the map while
  // the frame fills the screen anyway; resizing then would lose the reader's place on the
  // page when fullscreen ends, so the height is held until it does. The observer is
  // marked on the document, not the frame, so a frame that loads a new page is observed
  // again.
  function fitFrame(frame) {
    var doc;
    try {
      doc = frame.contentDocument;
    } catch (err) {
      return;
    }
    if (!doc || !doc.body || doc.location.href === "about:blank") return;
    var apply = function () {
      if (doc.fullscreenElement) return;
      var h = Math.ceil(doc.body.getBoundingClientRect().height);
      if (h > 0) frame.style.height = h + "px";
    };
    apply();
    if (!doc.pvFitObserved && frame.contentWindow.ResizeObserver) {
      doc.pvFitObserved = true;
      new frame.contentWindow.ResizeObserver(apply).observe(doc.body);
      doc.addEventListener("fullscreenchange", apply);
    }
  }

  // The bottom edge of Material's sticky header: the top of what a reader can see. Lower
  // at the top of the page, where the announcement bar sits above the header.
  function headerBottom() {
    var header = document.querySelector(".md-header");
    return header ? header.getBoundingClientRect().bottom : 0;
  }

  // Where the header's bottom edge rests once the page has scrolled past the announcement
  // bar: the height of the header itself, stuck to the top.
  function headerHeight() {
    var header = document.querySelector(".md-header");
    return header ? header.getBoundingClientRect().height : 0;
  }

  // A frame sized to its content never scrolls, so the two things the evidence atlas
  // (`src/earthpv/templates/pv_evidence_atlas.html`) does against its own viewport are
  // done against the site page's here.
  function bindAtlasFrame(frame) {
    var doc;
    try {
      doc = frame.contentDocument;
    } catch (err) {
      return;
    }
    if (!doc || !doc.body || doc.location.href === "about:blank" || doc.pvAtlasBound) return;
    doc.pvAtlasBound = true;

    // In-page links (the hero's "How the estimate is built" -> #method) scroll the site
    // page to their target, clear of the sticky header. Deferred one task so the atlas's
    // own handler has opened the <details> the link points at.
    doc.addEventListener("click", function (ev) {
      var a = ev.target.closest ? ev.target.closest('a[href^="#"]') : null;
      var id = a ? decodeURIComponent(a.getAttribute("href").slice(1)) : "";
      var target = id ? doc.getElementById(id) : null;
      if (!target) return;
      ev.preventDefault();
      setTimeout(function () {
        var top = window.scrollY + frame.getBoundingClientRect().top +
          target.getBoundingClientRect().top - headerHeight() - 8;
        window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
      }, 0);
    });

    // The shared tooltip (`showTip`) sits above the pointer and flips below it within
    // 150 px of the frame's top edge. The edge a reader sees is now the frame's top or
    // the header's bottom, whichever is lower, so the flip is decided again after every
    // move, before it paints (mutation observers run before rendering).
    var tip = doc.getElementById("tip");
    if (tip && frame.contentWindow.MutationObserver) {
      new frame.contentWindow.MutationObserver(function () {
        var y = parseFloat(tip.style.top);
        if (isNaN(y)) return;
        var seen = Math.max(0, headerBottom() - frame.getBoundingClientRect().top);
        tip.classList.toggle("below", y - seen < 150);
      }).observe(tip, { attributes: true, attributeFilter: ["style"] });
    }
  }

  function attach() {
    var frames = document.querySelectorAll(".embed iframe");
    for (var i = 0; i < frames.length; i++) {
      var frame = frames[i];
      if (!frame.dataset.pvThemeBound) {
        frame.dataset.pvThemeBound = "1";
        frame.addEventListener("load", syncFrame.bind(null, frame));
        if (frame.closest(".embed.fit")) frame.addEventListener("load", fitFrame.bind(null, frame));
      }
      syncFrame(frame); // already loaded from cache, or a no-op before load
      if (frame.closest(".embed.fit")) fitFrame(frame);
    }

    // The PV Atlas pages: sized to the whole atlas (see fitFrame).
    var atlases = document.querySelectorAll(".page-full-bleed.fit iframe");
    for (var j = 0; j < atlases.length; j++) {
      var atlas = atlases[j];
      if (!atlas.dataset.pvFitBound) {
        atlas.dataset.pvFitBound = "1";
        atlas.addEventListener("load", fitFrame.bind(null, atlas));
        atlas.addEventListener("load", bindAtlasFrame.bind(null, atlas));
      }
      fitFrame(atlas);
      bindAtlasFrame(atlas);
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
