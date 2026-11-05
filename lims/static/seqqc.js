// Sequencing QC overview: check verdicts (stacked bars), a metric's distribution (strip + box per row) and a
// scatter of two metrics. Plain SVG, no libraries. Colour carries only the QC verdict, always with a text label
// beside it (legend, tooltip, table), so nothing depends on colour alone.
(function () {
  const root = document.getElementById("sq");
  if (!root) return;
  const NS = "http://www.w3.org/2000/svg";
  const STATUS = ["fail", "warn", "pass", "not_assessed"];
  const SLABEL = {fail: "FAIL", warn: "WARN", pass: "PASS", not_assessed: "NA"};
  const SCOLOR = {fail: "#d03b3b", warn: "#fab219", pass: "#0ca30c", not_assessed: "#a3a29c"};
  const INK = "#1d2330", MUTED = "#6b7280", GRID = "#e6e8ec", SURF = "#ffffff";
  const $ = id => document.getElementById(id);
  const tip = $("sq-tip");
  let ROWS = [], LABELS = {};

  const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const label = k => LABELS[k] || k;
  const fmt = v => {
    if (v == null || !isFinite(v)) return "–";
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + "G";
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + "M";
    if (a >= 1e4) return (v / 1e3).toFixed(0) + "k";
    if (a >= 100 || Number.isInteger(v)) return v.toFixed(0);
    if (a >= 1) return v.toFixed(1);
    return v.toPrecision(2);
  };
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function svg(box, w, h, title) {
    box.innerHTML = "";
    const s = el("svg", {width: w, height: h, viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": title}, box);
    return s;
  }
  function text(s, x, y, str, o = {}) {
    const t = el("text", {x, y, fill: o.fill || MUTED, "font-size": o.size || 11, "text-anchor": o.anchor || "start",
                          "dominant-baseline": o.base || "auto", ...(o.weight ? {"font-weight": o.weight} : {})}, s);
    t.textContent = str;
    return t;
  }
  function showTip(evt, html) {
    tip.innerHTML = html; tip.hidden = false;
    const r = root.getBoundingClientRect(), pad = 14;
    let x = evt.clientX - r.left + pad, y = evt.clientY - r.top + pad;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    if (x + tw > r.width) x = evt.clientX - r.left - tw - pad;
    if (y + th > r.height) y = evt.clientY - r.top - th - pad;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => { tip.hidden = true; };
  const chip = st => `<span class="sq-chip" style="background:${SCOLOR[st]}"></span>${SLABEL[st]}`;
  const tubeUrl = r => "/samples/" + encodeURIComponent(r.sample_id) + "#seq-qc";
  const rowTip = (r, extra) => `<b>${esc(r.library || r.file || "library")}</b> · ${chip(r.status)}<br>` +
    `<span class="m">${esc(r.participant)} · ${esc(r.assay)} · ${esc(r.platform)} · No. ${esc(r.lims_number)}</span>` +
    (extra ? `<br>${extra}` : "") + (r.reason ? `<br><span class="m">${esc(r.reason)}</span>` : "");

  // ---------------------------------------------------------------- scales
  function scale(vals, log, px0, px1) {
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (log) { const pos = vals.filter(v => v > 0); lo = Math.min(...pos); hi = Math.max(...pos); }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (lo === hi) { const d = lo === 0 ? 1 : Math.abs(lo) * 0.1; lo -= d; hi += d; if (log && lo <= 0) lo = hi / 100; }
    if (!log) {   // a linear axis starts at zero when the data are not far from it
      if (lo >= 0 && lo < (hi - lo) * 0.6) lo = 0;
      const pad = (hi - lo) * 0.04; lo = lo === 0 ? 0 : lo - pad; hi += pad;
    }
    const f = log ? v => Math.log10(v) : v => v;
    const a = f(lo), b = f(hi);
    const map = v => px0 + (f(v) - a) / (b - a) * (px1 - px0);
    let ticks = [];
    if (log) {
      for (let e = Math.floor(a); e <= Math.ceil(b); e++) { const t = Math.pow(10, e); if (t >= lo * 0.999 && t <= hi * 1.001) ticks.push(t); }
      if (ticks.length < 2) ticks = [lo, hi];
    } else {
      const span = hi - lo, step0 = Math.pow(10, Math.floor(Math.log10(span / 5)));
      const step = [1, 2, 5, 10].map(m => m * step0).find(s => span / s <= 6) || step0 * 10;
      for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) ticks.push(+t.toPrecision(12));
    }
    return {map, ticks, lo, hi, ok: v => v != null && isFinite(v) && (!log || v > 0)};
  }

  // ---------------------------------------------------------------- data + filters
  const filters = [...root.querySelectorAll("select[data-f]")];
  function filtered() {
    const latest = $("sq-latest").checked;
    return ROWS.filter(r => (!latest || r.latest) && filters.every(f => !f.value || String(r[f.dataset.f]) === f.value));
  }
  function fillFilters() {
    filters.forEach(f => {
      const vals = [...new Set(ROWS.map(r => r[f.dataset.f]).filter(v => v != null && v !== ""))].sort();
      f.innerHTML = `<option value="">all</option>` + vals.map(v => `<option>${esc(v)}</option>`).join("");
    });
    const p = root.dataset.participant;
    if (p) { const f = filters.find(f => f.dataset.f === "participant"); if ([...f.options].some(o => o.value === p)) f.value = p; }
  }
  function metricKeys(rows) {
    const seen = new Map();
    rows.forEach(r => Object.keys(r.metrics).forEach(k => seen.set(k, (seen.get(k) || 0) + 1)));
    const known = Object.keys(LABELS).filter(k => seen.has(k));
    const other = [...seen.keys()].filter(k => !LABELS[k]).sort();
    return [...known, ...other];
  }
  function fillMetricSelect(sel, keys, prefer) {
    const cur = sel.value;
    sel.innerHTML = keys.map(k => `<option value="${esc(k)}">${esc(label(k))}</option>`).join("");
    sel.value = keys.includes(cur) ? cur : (prefer.find(k => keys.includes(k)) || keys[0] || "");
  }

  // ---------------------------------------------------------------- tiles
  function tiles(rows) {
    const n = {}; STATUS.forEach(s => n[s] = 0); rows.forEach(r => n[r.status]++);
    $("sq-tiles").innerHTML = `<div class="sq-tile"><div class="v">${rows.length}</div><div class="k">libraries</div></div>` +
      STATUS.map(s => `<div class="sq-tile"><div class="v">${n[s]}</div><div class="k">${chip(s)}</div></div>`).join("");
  }

  // ---------------------------------------------------------------- checks: stacked horizontal bars
  function drawChecks(rows) {
    const box = $("sq-checks");
    const counts = {};
    rows.forEach(r => Object.entries(r.checks).forEach(([c, st]) => {
      counts[c] = counts[c] || {fail: 0, warn: 0, pass: 0, not_assessed: 0, libs: {fail: [], warn: []}};
      counts[c][st]++; if (st === "fail" || st === "warn") counts[c].libs[st].push(r.library || r.file);
    }));
    const names = Object.keys(counts).sort((a, b) => (counts[b].fail * 1000 + counts[b].warn) - (counts[a].fail * 1000 + counts[a].warn) || a.localeCompare(b));
    if (!names.length) { box.innerHTML = `<p class="muted">No per-check verdicts in the selected results.</p>`; return; }
    const W = Math.max(300, box.clientWidth), narrow = W < 560;
    // wide: name left of its bar; narrow: name on its own line above the bar, so long names are never cut off
    const lw = narrow ? 0 : 190, bh = 16, gap = narrow ? 22 : 8, top = narrow ? 40 : 26, H = top + names.length * (bh + gap) + 4;
    const s = svg(box, W, H, "QC check verdicts");
    let lx = narrow ? 0 : lw;      // legend (always present: several series)
    STATUS.forEach(st => { el("rect", {x: lx, y: 4, width: 10, height: 10, rx: 2, fill: SCOLOR[st]}, s); text(s, lx + 14, 13, SLABEL[st], {fill: INK}); lx += 62; });
    const total = c => STATUS.reduce((a, st) => a + counts[c][st], 0);
    const max = Math.max(...names.map(total));
    const x0 = narrow ? 0 : lw, x1 = W - 34;
    names.forEach((c, i) => {
      const y = top + i * (bh + gap);
      if (narrow) text(s, 0, y - 5, c, {fill: INK, size: 11.5});
      else text(s, lw - 8, y + bh / 2, c, {anchor: "end", base: "middle", fill: INK, size: 11.5});
      let x = x0;
      STATUS.forEach(st => {
        const v = counts[c][st]; if (!v) return;
        const w = Math.max(1, (x1 - x0) * v / max - 2);
        const r = el("rect", {x, y, width: w, height: bh, rx: 3, fill: SCOLOR[st], class: "sq-hit"}, s);
        const libs = (counts[c].libs[st] || []).slice(0, 8);
        r.addEventListener("mousemove", e => showTip(e, `<b>${esc(c)}</b><br>${chip(st)}: ${v} of ${total(c)}` +
          (libs.length ? `<br><span class="m">${libs.map(esc).join("<br>")}${counts[c].libs[st].length > 8 ? "<br>…" : ""}</span>` : "")));
        r.addEventListener("mouseleave", hideTip);
        x += w + 2;
      });
      text(s, x + 4, y + bh / 2, String(total(c)), {base: "middle"});
    });
  }

  // ---------------------------------------------------------------- distribution: strip + box per group
  function quant(sorted, q) { const p = (sorted.length - 1) * q, i = Math.floor(p); return sorted[i] + (sorted[Math.min(i + 1, sorted.length - 1)] - sorted[i]) * (p - i); }
  function drawDist(rows) {
    const box = $("sq-dist"), key = $("sq-metric").value, grp = $("sq-group").value, log = $("sq-log").checked;
    const pts = rows.filter(r => r.metrics[key] != null);
    if (!key || !pts.length) { box.innerHTML = `<p class="muted">No values for this metric in the selection.</p>`; return; }
    const sc0 = scale(pts.map(r => r.metrics[key]), log, 0, 1);
    const use = pts.filter(r => sc0.ok(r.metrics[key]));
    const groups = [...new Set(use.map(r => grp ? String(r[grp]) : "all"))].sort();
    const W = Math.max(300, box.clientWidth), lw = grp ? Math.min(130, W * 0.25) : 16, rh = 34, top = 8, bottom = 30;
    const H = top + groups.length * rh + bottom;
    const s = svg(box, W, H, `Distribution of ${label(key)}`);
    const sc = scale(use.map(r => r.metrics[key]), log, lw + 8, W - 14);
    sc.ticks.forEach(t => { const x = sc.map(t); el("line", {x1: x, x2: x, y1: top, y2: H - bottom, stroke: GRID}, s); text(s, x, H - bottom + 14, fmt(t), {anchor: "middle"}); });
    text(s, (lw + W) / 2, H - 4, label(key) + (log ? " (log)" : ""), {anchor: "middle", fill: INK});
    groups.forEach((g, gi) => {
      const yc = top + gi * rh + rh / 2;
      if (grp) text(s, lw, yc, g, {anchor: "end", base: "middle", fill: INK});
      const mine = use.filter(r => (grp ? String(r[grp]) : "all") === g);
      const vals = mine.map(r => r.metrics[key]).sort((a, b) => a - b);
      if (vals.length >= 4) {      // box: IQR and median, recessive
        const q1 = sc.map(quant(vals, 0.25)), q3 = sc.map(quant(vals, 0.75)), md = sc.map(quant(vals, 0.5));
        el("rect", {x: q1, y: yc - 9, width: Math.max(1, q3 - q1), height: 18, rx: 3, fill: "#eef1f6", stroke: "#c9ced8"}, s);
        el("line", {x1: md, x2: md, y1: yc - 9, y2: yc + 9, stroke: INK, "stroke-width": 2}, s);
      }
      mine.forEach((r, i) => {
        const v = r.metrics[key], x = sc.map(v), jit = ((i * 7919) % 13 - 6) * 1.1;
        const c = el("circle", {cx: x, cy: yc + jit, r: 4.5, fill: SCOLOR[r.status], stroke: SURF, "stroke-width": 2, class: "sq-hit"}, s);
        c.addEventListener("mousemove", e => showTip(e, rowTip(r, `${esc(label(key))}: <b>${fmt(v)}</b>`)));
        c.addEventListener("mouseleave", hideTip);
        c.addEventListener("click", () => { location.href = tubeUrl(r); });
      });
    });
    const skipped = pts.length - use.length;
    if (skipped) text(s, W - 14, top + 10, `${skipped} value(s) ≤ 0 not shown on a log scale`, {anchor: "end"});
  }

  // ---------------------------------------------------------------- scatter: two metrics, coloured by verdict
  function drawScatter(rows) {
    const box = $("sq-scatter"), kx = $("sq-x").value, ky = $("sq-y").value, lx = $("sq-xlog").checked, ly = $("sq-ylog").checked;
    const pts0 = rows.filter(r => r.metrics[kx] != null && r.metrics[ky] != null);
    if (!kx || !ky || !pts0.length) { box.innerHTML = `<p class="muted">No library has both metrics in the selection.</p>`; return; }
    const W = Math.max(300, box.clientWidth), H = Math.min(420, Math.max(260, W * 0.55)), L = 56, R = 14, T = 42, B = 40;
    const s = svg(box, W, H, `${label(ky)} against ${label(kx)}`);
    const sx = scale(pts0.map(r => r.metrics[kx]), lx, L, W - R), sy = scale(pts0.map(r => r.metrics[ky]), ly, H - B, T);
    const pts = pts0.filter(r => sx.ok(r.metrics[kx]) && sy.ok(r.metrics[ky]));
    sx.ticks.forEach(t => { const x = sx.map(t); el("line", {x1: x, x2: x, y1: T, y2: H - B, stroke: GRID}, s); text(s, x, H - B + 14, fmt(t), {anchor: "middle"}); });
    sy.ticks.forEach(t => { const y = sy.map(t); el("line", {x1: L, x2: W - R, y1: y, y2: y, stroke: GRID}, s); text(s, L - 6, y, fmt(t), {anchor: "end", base: "middle"}); });
    text(s, (L + W - R) / 2, H - 6, label(kx) + (lx ? " (log)" : ""), {anchor: "middle", fill: INK});
    text(s, L, 32, label(ky) + (ly ? " (log)" : ""), {fill: INK});
    let gx = L;     // legend on its own row, so it never collides with the axis title on a narrow screen
    STATUS.forEach(st => { el("rect", {x: gx, y: 3, width: 10, height: 10, rx: 2, fill: SCOLOR[st]}, s); text(s, gx + 14, 12, SLABEL[st], {fill: INK}); gx += 62; });
    // worst verdicts drawn last so they sit on top
    pts.sort((a, b) => STATUS.indexOf(b.status) - STATUS.indexOf(a.status)).forEach(r => {
      const c = el("circle", {cx: sx.map(r.metrics[kx]), cy: sy.map(r.metrics[ky]), r: 5, fill: SCOLOR[r.status], stroke: SURF, "stroke-width": 2, class: "sq-hit"}, s);
      c.addEventListener("mousemove", e => showTip(e, rowTip(r, `${esc(label(kx))}: <b>${fmt(r.metrics[kx])}</b><br>${esc(label(ky))}: <b>${fmt(r.metrics[ky])}</b>`)));
      c.addEventListener("mouseleave", hideTip);
      c.addEventListener("click", () => { location.href = tubeUrl(r); });
    });
  }

  // ---------------------------------------------------------------- table (also the accessible view of the charts)
  function drawTable(rows) {
    const key = $("sq-metric").value;
    const sorted = [...rows].sort((a, b) => STATUS.indexOf(a.status) - STATUS.indexOf(b.status) || a.participant.localeCompare(b.participant) || a.library.localeCompare(b.library));
    $("sq-table").innerHTML = `<table class="compact"><thead><tr><th>Result</th><th>Library</th><th>Tube</th><th>Assay · platform</th>` +
      `<th>Failed / warned checks</th><th>${esc(label(key))}</th><th>Workflow</th></tr></thead><tbody>` +
      sorted.map(r => {
        const bad = Object.entries(r.checks).filter(([, st]) => st === "fail" || st === "warn").map(([c, st]) => `<span class="tag qc-${st}">${esc(c)}</span>`).join(" ");
        return `<tr><td><span class="tag qc-${r.status}">${SLABEL[r.status]}</span></td><td>${esc(r.library || r.file || "–")}</td>` +
          `<td><a href="${tubeUrl(r)}">${esc(r.participant)} · No. ${esc(r.lims_number)}</a><br><span class="muted small">${esc(r.material)}</span></td>` +
          `<td>${esc(r.assay)} · ${esc(r.platform)}</td><td>${bad || '<span class="muted">none</span>'}${r.reason ? `<br><span class="muted small">${esc(r.reason)}</span>` : ""}</td>` +
          `<td>${fmt(r.metrics[key])}</td><td class="small">${esc(r.workflow)} ${esc(r.version)}<br><span class="muted">${esc(r.recorded_at)}</span></td></tr>`;
      }).join("") + `</tbody></table>`;
  }

  // ---------------------------------------------------------------- wiring
  function render() {
    hideTip();
    const rows = filtered();
    const keys = metricKeys(rows);
    fillMetricSelect($("sq-metric"), keys, ["mean_coverage", "total_reads", "pct_q30"]);
    fillMetricSelect($("sq-x"), keys, ["total_reads", "total_bases"]);
    fillMetricSelect($("sq-y"), keys, ["mean_coverage", "pct_duplication", "pct_q30"]);
    tiles(rows); drawChecks(rows); drawDist(rows); drawScatter(rows); drawTable(rows);
  }
  root.addEventListener("change", e => { if (e.target.matches("select, input")) render(); });
  let t; window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(render, 150); });
  fetch(root.dataset.src, {credentials: "same-origin"}).then(r => r.json()).then(d => {
    ROWS = d.rows; LABELS = d.labels || {};
    ["sq-log", "sq-xlog"].forEach(id => { $(id).checked = false; });
    fillFilters();
    const keys = metricKeys(ROWS);
    if (keys.includes("total_reads")) $("sq-xlog").checked = true;   // read counts span orders of magnitude
    render();
  }).catch(() => { $("sq-tiles").innerHTML = `<p class="muted">Could not load the QC data.</p>`; });
})();
