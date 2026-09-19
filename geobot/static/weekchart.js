// 📈 Week progress: crosshair + tooltip over the server-rendered SVG. Listens on
// document (like sort.js) rather than binding per chart, so the 60s htmx poll can
// replace the whole fragment without anything to re-initialise.
(function () {
  var open = null;  // the .weekchart currently showing a tooltip

  function dots(chart) { return chart.querySelectorAll("circle[data-day]"); }

  function hide() {
    if (!open) return;
    var cross = open.querySelector(".cross"), tip = open.querySelector(".chart-tip");
    if (cross) cross.style.display = "";
    if (tip) tip.hidden = true;
    [].forEach.call(dots(open), function (c) { c.setAttribute("r", 3); });
    open = null;
  }

  function show(chart, e) {
    var svg = chart.querySelector("svg"), tip = chart.querySelector(".chart-tip");
    var cross = chart.querySelector(".cross");
    if (!svg || !tip || !cross) return;
    var xs;
    try { xs = JSON.parse(svg.dataset.x || "[]"); } catch (err) { return; }
    var days = JSON.parse(svg.dataset.days || "[]");
    if (!xs.length) return;

    // Once JS is driving, the per-dot <title> would double up as a second,
    // slower tooltip — drop them the first time this chart is hovered.
    if (!chart.dataset.hover) {
      chart.dataset.hover = "1";
      [].forEach.call(svg.querySelectorAll("circle > title"), function (t) { t.remove(); });
    }

    var box = svg.getBoundingClientRect();
    var scale = box.width / svg.viewBox.baseVal.width;
    var at = (e.clientX - box.left) / scale;            // pointer, in viewBox units
    var day = 0;
    for (var i = 1; i < xs.length; i++) {
      if (Math.abs(xs[i] - at) < Math.abs(xs[day] - at)) day = i;
    }

    var rows = [];
    [].forEach.call(dots(chart), function (c) {
      var on = +c.dataset.day === day;
      c.setAttribute("r", on ? 4.5 : 3);
      if (on) rows.push({ name: c.dataset.name, value: +c.dataset.value,
                          colour: c.getAttribute("fill") });
    });
    rows.sort(function (a, b) { return b.value - a.value; });

    tip.textContent = "";
    var head = document.createElement("div");
    head.className = "tip-day";
    head.textContent = days[day] || "";
    tip.appendChild(head);
    rows.forEach(function (r) {
      var row = document.createElement("div"), sw = document.createElement("span"),
          name = document.createElement("span"), val = document.createElement("b");
      row.className = "tip-row";
      sw.className = "swatch";
      sw.style.background = r.colour;
      name.textContent = r.name;
      val.textContent = r.value.toLocaleString("en-US");
      row.appendChild(sw); row.appendChild(name); row.appendChild(val);
      tip.appendChild(row);
    });

    cross.setAttribute("x1", xs[day]);
    cross.setAttribute("x2", xs[day]);
    cross.style.display = "block";
    tip.hidden = false;

    // Place it beside the crosshair, flipping to the other side and clamping
    // rather than letting it hang off the card.
    var crect = chart.getBoundingClientRect();
    var px = box.left - crect.left + xs[day] * scale;
    var left = px + 12;
    if (left + tip.offsetWidth > crect.width) left = px - 12 - tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(left, crect.width - tip.offsetWidth)) + "px";
    var top = box.top - crect.top + +cross.getAttribute("y1") * scale;
    tip.style.top = Math.max(0, Math.min(top, crect.height - tip.offsetHeight)) + "px";
    open = chart;
  }

  document.addEventListener("pointermove", function (e) {
    var chart = e.target.closest ? e.target.closest(".weekchart") : null;
    if (!chart) { hide(); return; }
    if (open && open !== chart) hide();
    show(chart, e);
  });
  // Moving anywhere off the chart already hides it; these two cover the pointer
  // leaving the window entirely, and the poll swapping the SVG out from under us.
  document.documentElement.addEventListener("pointerleave", hide);
  document.body.addEventListener("htmx:beforeSwap", hide);
})();
