/* Click a table header to sort the table. No dependency: the site ships no third-party
   JavaScript and one small sorter is cheaper than vendoring a library and its licence.

   Three sort modes, picked per column from what is actually in it:

   - VERDICT, when the cells carry `.outcome` spans. Alphabetical would interleave the
     register's four verdicts meaninglessly ("partial, rejected, shipped, superseded"), so
     these sort by outcome instead: shipped, partial, rejected, superseded. That ordering
     is the point of the column.
   - NUMERIC, when every non-empty cell parses as a number once a leading sign, a trailing
     percent and thousands separators are stripped. Covers the register's deltas (+0.0234)
     and counts.
   - TEXT otherwise, with `localeCompare` and numeric collation, so "10 of 30" sorts after
     "9 of 30" rather than before it.

   Empty cells always sink to the bottom, in both directions: a missing value is not a
   small one. */
(function () {
  var RANK = { shipped: 0, works: 0, partial: 1, mixed: 1,
               rejected: 2, negative: 2, superseded: 3, open: 3 };

  function cellText(row, i) {
    var c = row.cells[i];
    return c ? c.textContent.trim() : "";
  }

  function outcomeRank(row, i) {
    var c = row.cells[i];
    if (!c) return null;
    var el = c.querySelector(".outcome");
    if (!el) return null;
    var key = el.textContent.trim().toLowerCase();
    if (key in RANK) return RANK[key];
    var m = (el.className.match(/outcome\s+(\w+)/) || [])[1];
    return m && m in RANK ? RANK[m] : 99;
  }

  function asNumber(s) {
    if (!s) return null;
    var t = s.replace(/[,\s]/g, "").replace(/%$/, "").replace(/^\+/, "");
    if (!/^-?\d*\.?\d+$/.test(t)) return null;
    return parseFloat(t);
  }

  function columnMode(rows, i) {
    var sawOutcome = false, sawValue = false;
    for (var r = 0; r < rows.length; r++) {
      if (outcomeRank(rows[r], i) !== null) sawOutcome = true;
      var txt = cellText(rows[r], i);
      if (!txt) continue;
      sawValue = true;
      if (asNumber(txt) === null) return sawOutcome ? "verdict" : "text";
    }
    if (sawOutcome) return "verdict";
    return sawValue ? "number" : "text";
  }

  function sortTable(table, col, dir) {
    var body = table.tBodies[0];
    if (!body) return;
    var rows = Array.prototype.slice.call(body.rows);
    var mode = columnMode(rows, col);
    var keyed = rows.map(function (row, idx) {
      var txt = cellText(row, col);
      var key;
      if (mode === "verdict") key = outcomeRank(row, col);
      else if (mode === "number") key = asNumber(txt);
      else key = txt;
      return { row: row, key: key, txt: txt, idx: idx };
    });
    keyed.sort(function (a, b) {
      var ae = a.txt === "" || a.key === null, be = b.txt === "" || b.key === null;
      if (ae !== be) return ae ? 1 : -1;      // blanks sink, whichever way we sort
      if (ae && be) return a.idx - b.idx;
      var c;
      if (mode === "text") c = String(a.key).localeCompare(String(b.key), undefined,
                                                           { numeric: true });
      else c = a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
      if (c === 0) return a.idx - b.idx;      // stable
      return dir === "asc" ? c : -c;
    });
    keyed.forEach(function (k) { body.appendChild(k.row); });
  }

  function wire(table) {
    if (table.dataset.sortable === "on") return;
    var head = table.tHead;
    if (!head || !head.rows.length || !table.tBodies.length) return;
    if (table.tBodies[0].rows.length < 3) return;   // not worth sorting
    table.dataset.sortable = "on";
    var ths = Array.prototype.slice.call(head.rows[0].cells);
    ths.forEach(function (th, i) {
      th.classList.add("sortable-th");
      th.tabIndex = 0;
      th.setAttribute("role", "button");
      th.setAttribute("aria-sort", "none");
      var go = function () {
        var dir = th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
        ths.forEach(function (o) { o.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
        sortTable(table, i, dir);
      };
      th.addEventListener("click", go);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
      });
    });
  }

  function wireAll() {
    document.querySelectorAll(".md-typeset table:not([class])").forEach(wire);
  }

  if (typeof document$ !== "undefined" && document$.subscribe) document$.subscribe(wireAll);
  else if (document.readyState !== "loading") wireAll();
  else document.addEventListener("DOMContentLoaded", wireAll);
})();
