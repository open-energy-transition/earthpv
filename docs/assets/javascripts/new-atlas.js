/* contribute/new-atlas: when the globe sends someone here for a country
 * (?country=Brazil&iso3=BRA&bbox=-74.1,-33.8,-34.7,5.3), write that country into the page's
 * commands, so what they copy is ready to run. Without a country the placeholders stay.
 */
(function () {
  "use strict";

  function fill() {
    var banner = document.querySelector("[data-new-atlas]");
    if (!banner) return;
    var q = new URLSearchParams(window.location.search);
    var country = (q.get("country") || "").trim().slice(0, 80);
    if (!country) return;

    var iso3 = (q.get("iso3") || "").toUpperCase();
    var bbox = q.get("bbox") || "";
    var key = country.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    var values = { YOUR_COUNTRY: country, YOUR_AOI: key };
    if (/^[A-Z]{3}$/.test(iso3)) values.YOUR_ISO3 = iso3;
    if (/^-?[\d.]+(,-?[\d.]+){3}$/.test(bbox)) values.YOUR_BBOX = bbox;

    var pattern = new RegExp(Object.keys(values).join("|"), "g");
    var article = document.querySelector(".md-content__inner") || document.body;
    var walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT);
    var hits = [];
    while (walker.nextNode()) {
      pattern.lastIndex = 0;
      if (pattern.test(walker.currentNode.nodeValue)) hits.push(walker.currentNode);
    }
    hits.forEach(function (node) {
      node.nodeValue = node.nodeValue.replace(pattern, function (m) { return values[m]; });
    });

    banner.querySelector("[data-new-atlas-country]").textContent = country;
    banner.hidden = false;
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fill);
  else fill();
})();
