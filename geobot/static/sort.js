// Click any column header to sort its table. Re-applies after each htmx poll
// (which replaces the table) so the chosen sort survives the 60s refresh.
(function () {
  function num(s) { var n = parseFloat(s.replace(/[^0-9.\-]/g, "")); return (/\d/.test(s) && !isNaN(n)) ? n : null; }
  function sort(table, col, dir) {
    var tb = table.tBodies[0]; if (!tb) return;
    [].slice.call(tb.rows).sort(function (a, b) {
      var x = a.cells[col].textContent.trim(), y = b.cells[col].textContent.trim();
      var nx = num(x), ny = num(y), r = (nx !== null && ny !== null) ? nx - ny : x.localeCompare(y);
      return dir < 0 ? -r : r;
    }).forEach(function (row) { tb.appendChild(row); });
    var ths = table.tHead.rows[0].cells;
    for (var i = 0; i < ths.length; i++) {
      var base = ths[i].dataset.label || (ths[i].dataset.label = ths[i].textContent);
      ths[i].textContent = base + (i === col ? (dir < 0 ? " ▼" : " ▲") : "");
    }
  }
  document.addEventListener("click", function (e) {
    var th = e.target.closest("th"); if (!th) return;
    var table = th.closest("table"), box = th.closest("[hx-get]"); if (!table || !box) return;
    var col = [].indexOf.call(th.parentNode.cells, th);
    var dir = (box.dataset.sortCol == col && box.dataset.sortDir == "1") ? -1 : 1;
    box.dataset.sortCol = col; box.dataset.sortDir = dir > 0 ? "1" : "-1";
    sort(table, col, dir);
  });
  document.body.addEventListener("htmx:afterSettle", function (e) {
    var box = e.target; if (box.dataset.sortCol == null) return;
    var table = box.querySelector("table"); if (table) sort(table, +box.dataset.sortCol, box.dataset.sortDir == "-1" ? -1 : 1);
  });
})();
