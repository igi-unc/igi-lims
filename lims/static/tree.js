// Interactive provenance tree (SVG).
// Input: window.TREE, nested {sample, children}; a node with sample=null is either a participant (virtual root)
// or a collection {collection: {...}}, the specimen as received, which is not a tube.
// Optional: window.HIGHLIGHT (sample ID), window.MEANINGS, window.ATTRS, window.ATTR_LABELS,
// window.ORIENT = "vertical" (root at top) or "horizontal" (root at left).
//
// Interaction: hover shows a tooltip; clicking a tube pins a detail panel (#tree-panel) or opens the tube page;
// clicking a collection opens it. Every box with children has a +/- handle that collapses its branch.
// Sibling tubes of the same fraction-material with no children of their own are stacked into one
// "PFM-CPU x10" box; click it to expand. A toolbar offers expand/collapse all, grouping and zoom.
(function () {
  const data = window.TREE, highlight = window.HIGHLIGHT || "", M = window.MEANINGS || {};
  const svg = document.getElementById("tree-svg"), tip = document.getElementById("tree-tip"), panel = document.getElementById("tree-panel");
  if (!svg || !data) return;
  const vertical = (window.ORIENT || "horizontal") === "vertical";
  const NODE_W = 100, NODE_H = 22, PAD = 12;
  const GAP_X = vertical ? 8 : 34, GAP_Y = vertical ? 30 : 6;   // gap along the leaf axis / the depth axis
  const colors = { Available: "#dcfce7", Depleted: "#fee2e2", Shipped: "#dbeafe", Destroyed: "#e5e7eb", "In use": "#fef3c7" };
  const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  const pad2 = n => String(n).padStart(2, "0");
  const tubeLabel = s => `${s.fraction_code}-${s.material_code}-${pad2(s.aliquot)}`;

  // ---------------------------------------------------------------- model
  let grouping = true;
  const collapsed = new Set();      // keys of collapsed nodes (groups start collapsed)
  let model;

  function build(node, path) {
    const kids = (node.children || []).map((c, i) => build(c, path + "/" + i));
    if (node.sample) return { kind: "tube", s: node.sample, key: "s:" + node.sample.sample_id, kids };
    if (node.collection) return { kind: "collection", c: node.collection, key: "c:" + node.collection.collection_id, kids };
    return { kind: "root", label: node.participant || "root", key: "r:" + path, kids };
  }

  function groupKids(n) {
    // stack leaf tubes that share fraction-material (2 or more) into one group node, in first-seen order
    if (!grouping) return n.kids;
    const out = [], groups = {};
    n.kids.forEach(k => {
      if (k.kind === "tube" && !k.kids.length) {
        const fm = k.s.fraction_code + "-" + k.s.material_code;
        if (!groups[fm]) { groups[fm] = { kind: "group", fm, key: n.key + "|g:" + fm, members: [] }; out.push(groups[fm]); }
        groups[fm].members.push(k);
      } else out.push(k);
    });
    return out.map(g => (g.kind === "group" && g.members.length === 1) ? g.members[0] : g);
  }

  function visibleKids(n) {
    if (collapsed.has(n.key)) return [];
    if (n.kind === "group") return n.members;
    return groupKids(n);
  }
  function hasKids(n) { return n.kind === "group" ? true : n.kids.length > 0; }
  function countTubes(n) {
    if (n.kind === "group") return n.members.length;
    return n.kids.reduce((a, k) => a + (k.kind === "tube" ? 1 : 0) + countTubes(k), 0);
  }

  function walk(n, f) { f(n); (n.kind === "group" ? n.members : n.kids).forEach(k => walk(k, f)); }

  function defaults() {
    collapsed.clear();
    // groups start collapsed, except the one holding the highlighted tube
    walk(model, n => { if (n.kind !== "group") groupKids(n).forEach(k => { if (k.kind === "group") collapsed.add(k.key); }); });
    if (highlight) {
      const path = [];
      (function find(n, trail) {
        if (n.kind === "tube" && n.s.sample_id === highlight) { path.push(...trail); return true; }
        const kids = n.kind === "group" ? n.members : groupKids(n);
        return kids.some(k => find(k, trail.concat([k])));
      })(model, []);
      path.forEach(n => collapsed.delete(n.key));
    }
  }

  // ---------------------------------------------------------------- layout + render
  let scale = 1, userZoom = false;   // until the user zooms, every render fits the tree to the available width
  let nodes = [], links = [];
  const BREADTH = vertical ? NODE_W : NODE_H, SEP = vertical ? GAP_X : GAP_Y;

  // Compact ("tidy") layout: each subtree is packed against its left sibling as closely as their outlines allow
  // at every depth, so a deep narrow branch does not reserve a whole column for each leaf of its neighbours.
  function layout() {
    nodes = []; links = [];
    const place = (n, depth, parent) => {
      const v = { n, depth, parent };
      nodes.push(v);
      if (parent) links.push([parent, v]);
      v.kids = visibleKids(n).map(k => place(k, depth + 1, v));
      return v;
    };
    const root = place(model, 0, null);
    const outline = v => {                       // returns {L, R}: left/right extent per depth, relative to v
      if (!v.kids.length) { v.off = []; return { L: [0], R: [BREADTH] }; }
      const cs = v.kids.map(outline), offs = [0];
      const accL = cs[0].L.slice(), accR = cs[0].R.slice();
      for (let i = 1; i < cs.length; i++) {
        const c = cs[i];
        let shift = -Infinity;
        for (let d = 0; d < Math.min(accR.length, c.L.length); d++) shift = Math.max(shift, accR[d] - c.L[d] + SEP);
        offs.push(shift);
        c.R.forEach((r, d) => { accR[d] = r + shift; });
        c.L.forEach((l, d) => { if (accL[d] === undefined) accL[d] = l + shift; });
      }
      const centre = (offs[0] + offs[offs.length - 1]) / 2;   // parent sits over the middle of its children
      v.off = offs.map(o => o - centre);
      return { L: [0].concat(accL.map(a => a - centre)), R: [BREADTH].concat(accR.map(a => a - centre)) };
    };
    outline(root);
    const assign = (v, b) => { v.b = b; v.kids.forEach((k, i) => assign(k, b + v.off[i])); };
    assign(root, 0);
    const minB = Math.min(...nodes.map(v => v.b));
    nodes.forEach(v => { v.b -= minB; });
    return { span: Math.max(...nodes.map(v => v.b)) + BREADTH, maxDepth: Math.max(...nodes.map(v => v.depth)) };
  }

  function statusFill(list) {
    const counts = {};
    list.forEach(s => { const k = s.deleted_at ? "deleted" : s.status; counts[k] = (counts[k] || 0) + 1; });
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    return { counts, fill: top === "deleted" ? "#f3f4f6" : (colors[top] || "#fff"), mixed: Object.keys(counts).length > 1 };
  }

  function render() {
    const { span, maxDepth } = layout();
    let W, H, x, y;
    if (vertical) {
      W = span + 2 * PAD; H = (maxDepth + 1) * (NODE_H + GAP_Y) - GAP_Y + 2 * PAD + 8;
      x = v => v.b + PAD; y = v => v.depth * (NODE_H + GAP_Y) + PAD;
    } else {
      W = (maxDepth + 1) * (NODE_W + GAP_X) - GAP_X + 2 * PAD + 12; H = span + 2 * PAD;
      x = v => v.depth * (NODE_W + GAP_X) + PAD; y = v => v.b + PAD;
    }
    if (!userZoom) {
      const avail = (svg.parentElement.clientWidth || W) - 4;
      scale = Math.max(0.6, Math.min(1, avail / W));
    }
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", Math.round(W * scale)); svg.setAttribute("height", Math.round(H * scale));
    let out = "";
    links.forEach(([a, b]) => {
      if (vertical) {
        const x1 = x(a) + NODE_W / 2, y1 = y(a) + NODE_H, x2 = x(b) + NODE_W / 2, y2 = y(b);
        out += `<path d="M${x1},${y1} C${x1},${y1 + GAP_Y / 2} ${x2},${y2 - GAP_Y / 2} ${x2},${y2}" fill="none" stroke="#b6bcc6" stroke-width="1.2"/>`;
      } else {
        const x1 = x(a) + NODE_W, y1 = y(a) + NODE_H / 2, x2 = x(b), y2 = y(b) + NODE_H / 2;
        out += `<path d="M${x1},${y1} C${x1 + GAP_X / 2},${y1} ${x2 - GAP_X / 2},${y2} ${x2},${y2}" fill="none" stroke="#b6bcc6" stroke-width="1.2"/>`;
      }
    });
    nodes.forEach((v, i) => {
      const n = v.n;
      let fill, stroke = "#9ca3af", sw = 1, text, dark = false, stack = "";
      if (n.kind === "root") { fill = "#1f5fbf"; text = n.label; dark = true; }
      else if (n.kind === "collection") { fill = "#0f5257"; text = n.c.label; dark = true; }
      else if (n.kind === "group") {
        const st = statusFill(n.members.map(m => m.s));
        fill = st.fill; text = `${n.fm} ×${n.members.length}`;
        if (n.members.some(m => m.s.sample_id === highlight)) { stroke = "#1f5fbf"; sw = 2.2; }
        if (collapsed.has(n.key)) stack = `<rect x="4" y="-4" width="${NODE_W}" height="${NODE_H}" rx="4" fill="${fill}" stroke="#9ca3af"/>` +
                                          `<rect x="2" y="-2" width="${NODE_W}" height="${NODE_H}" rx="4" fill="${fill}" stroke="#9ca3af"/>`;
      } else {
        fill = n.s.deleted_at ? "#f3f4f6" : (colors[n.s.status] || "#fff"); text = tubeLabel(n.s);
        if (n.s.sample_id === highlight) { stroke = "#1f5fbf"; sw = 2.2; }
      }
      const clickable = n.kind !== "root";
      out += `<g class="node" data-i="${i}" transform="translate(${x(v)},${y(v)})" style="cursor:${clickable ? "pointer" : "default"}">` + stack +
        `<rect width="${NODE_W}" height="${NODE_H}" rx="4" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>` +
        `<text x="${NODE_W / 2}" y="15" text-anchor="middle" font-size="${n.kind === "tube" || n.kind === "group" ? 10.5 : 9.5}" font-family="ui-monospace,Menlo,monospace" font-weight="600" fill="${dark ? "#fff" : "#1d2330"}">${esc(text)}</text></g>`;
      if (hasKids(n) && n.kind !== "group") {
        const closed = collapsed.has(n.key);
        const cx = vertical ? x(v) + NODE_W / 2 : x(v) + NODE_W + 7, cy = vertical ? y(v) + NODE_H + 7 : y(v) + NODE_H / 2;
        const hidden = closed ? countTubes(n) : 0;
        out += `<g class="tgl" data-i="${i}" style="cursor:pointer" role="button" aria-label="${closed ? "expand" : "collapse"}">` +
          `<circle cx="${cx}" cy="${cy}" r="6.5" fill="#fff" stroke="#6b7280"/>` +
          `<text x="${cx}" y="${cy + 3.5}" text-anchor="middle" font-size="10" font-weight="700" fill="#374151">${closed ? "+" : "−"}</text>` +
          (closed && hidden ? `<text x="${cx + 10}" y="${cy + 3.5}" font-size="9" fill="#6b7280">${hidden}</text>` : "") + `</g>`;
      }
    });
    svg.innerHTML = out;
    if (zoomOut) zoomOut.textContent = Math.round(scale * 100) + "%";
  }

  // ---------------------------------------------------------------- tooltip + panel content
  const meaning = (cat, code) => (M[cat] && M[cat][code]) ? `${code} – ${M[cat][code]}` : code;
  const ATTRS = window.ATTRS || {}, AL = window.ATTR_LABELS || {};
  const attrLines = (s, max) => Object.entries(ATTRS[s.sample_id] || {}).slice(0, max).map(([k, v]) => `<div><span class="muted">${esc(AL[k] || k)}:</span> ${esc(v)}</div>`).join("");
  const attrRows = s => Object.entries(ATTRS[s.sample_id] || {}).map(([k, v]) => `<tr><th>${esc(AL[k] || k)}</th><td>${esc(v)}</td></tr>`).join("");
  const loc = s => [s.freezer, s.rack, s.box, s.position].filter(v => v && v !== "NA").join(" / ") || "—";
  function summary(s) {
    return `<div class="t"><code>${esc(s.sample_id)}</code></div>` +
      `<div><span class="status ${esc(s.status)}">${esc(s.status)}</span>${s.deleted_at ? " <b>deleted</b>" : ""}</div>` +
      `<div>${esc(meaning("fraction", s.fraction_code))}</div><div>${esc(meaning("material", s.material_code))}</div>` +
      `<div>${s.quantity != null ? esc(s.quantity) + " " + esc(s.unit || "") : "—"} · ${esc(loc(s))}</div>` +
      `<div class="muted">${esc(s.created_datetime || "")} ${esc(s.created_by || "")}${s.sop_code ? " · " + esc(s.sop_code) : ""}</div>` + attrLines(s, 6);
  }
  function groupSummary(g) {
    const st = statusFill(g.members.map(m => m.s)).counts;
    return `<div class="t">${esc(g.fm)} × ${g.members.length}</div>` +
      `<div>${esc(meaning("fraction", g.members[0].s.fraction_code))}</div><div>${esc(meaning("material", g.members[0].s.material_code))}</div>` +
      `<div>aliquots ${g.members.map(m => pad2(m.s.aliquot)).join(", ")}</div>` +
      `<div>${Object.entries(st).map(([k, n]) => `${n} ${esc(k)}`).join(" · ")}</div>` +
      `<div class="muted">click to ${collapsed.has(g.key) ? "show each tube" : "stack them again"}</div>`;
  }
  function detail(s) {
    const rows = [["Specimen", meaning("specimen", s.specimen_code)], ["Fraction", meaning("fraction", s.fraction_code)],
      ["Material", meaning("material", s.material_code)], ["Received", s.received_date], ["Parent", s.parent_id || "none (first generation)"],
      ["Status", s.status], ["Quantity", s.quantity != null ? s.quantity + " " + (s.unit || "") : ""], ["Location", loc(s)],
      ["Processed", (s.created_datetime || "") + " " + (s.created_by || "") + (s.sop_code ? " · " + s.sop_code : "")],
      ["Biobank", meaning("biobank_source", s.biobank_source)], ["Notes", s.notes || ""]];
    return `<div class="t"><code>${esc(s.sample_id)}</code> <span class="status ${esc(s.status)}">${esc(s.status)}</span></div>` +
      `<div class="label-wrap"><img class="label-img" src="/samples/${encodeURIComponent(s.sample_id)}/label.svg" alt="label"></div>` +
      `<table class="compact">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("")}${attrRows(s)}</table>` +
      `<p><a class="btn secondary" href="/samples/${s.sample_id}">Open tube page</a> ` +
      `<button type="button" class="small secondary" id="tree-panel-close">close</button></p>`;
  }
  function collSummary(c) {
    return `<div class="t">Collection ${esc(c.label)}</div><div>${esc(meaning("specimen", c.specimen_code))}</div>` +
      `<div>received ${esc(c.received_date)}${c.quantity != null ? " · " + esc(c.quantity) + " " + esc(c.unit || "") : ""}</div>` +
      `<div class="muted">the specimen as received; not a tube. Click to open it.</div>`;
  }

  // ---------------------------------------------------------------- events (delegated, survive re-render)
  const nodeOf = el => { const g = el.closest("g.node, g.tgl"); return g ? { g, v: nodes[+g.dataset.i], tgl: g.classList.contains("tgl") } : null; };
  function toggle(n) { collapsed.has(n.key) ? collapsed.delete(n.key) : collapsed.add(n.key); render(); }
  svg.addEventListener("mousemove", ev => {
    if (!tip) return;
    const hit = nodeOf(ev.target);
    if (!hit || hit.tgl || hit.v.n.kind === "root") { tip.hidden = true; return; }
    const n = hit.v.n;
    tip.innerHTML = n.kind === "tube" ? summary(n.s) : n.kind === "group" ? groupSummary(n) : collSummary(n.c);
    tip.hidden = false;
    const r = (svg.closest(".card") || svg.parentElement).getBoundingClientRect();
    tip.style.left = (ev.clientX - r.left + 14) + "px"; tip.style.top = (ev.clientY - r.top + 14) + "px";
  });
  svg.addEventListener("mouseleave", () => { if (tip) tip.hidden = true; });
  svg.addEventListener("click", ev => {
    const hit = nodeOf(ev.target);
    if (!hit) return;
    const n = hit.v.n;
    if (hit.tgl || n.kind === "group") { toggle(n); return; }
    if (n.kind === "collection") { window.location = "/collections/" + n.c.collection_id; return; }
    if (n.kind !== "tube") return;
    if (!panel) { window.location = "/samples/" + n.s.sample_id; return; }
    panel.innerHTML = detail(n.s); panel.hidden = false;
    document.getElementById("tree-panel-close").onclick = () => { panel.hidden = true; };
  });

  // ---------------------------------------------------------------- toolbar
  let zoomOut = null;
  (function toolbar() {
    const wrap = svg.parentElement;
    const bar = document.createElement("div");
    bar.className = "tree-toolbar";
    bar.innerHTML =
      `<button type="button" class="small secondary" data-act="expand">Expand all</button>` +
      `<button type="button" class="small secondary" data-act="collapse">Collapse to collections</button>` +
      `<label class="small"><input type="checkbox" data-act="group" checked> stack same-type aliquots</label>` +
      `<span class="zoom"><button type="button" class="small secondary" data-act="out" aria-label="zoom out">−</button>` +
      `<span class="pct"></span><button type="button" class="small secondary" data-act="in" aria-label="zoom in">+</button>` +
      `<button type="button" class="small secondary" data-act="fit">Fit</button></span>`;
    wrap.parentElement.insertBefore(bar, wrap);
    zoomOut = bar.querySelector(".pct");
    bar.addEventListener("click", ev => {
      const act = ev.target.dataset && ev.target.dataset.act;
      if (act === "expand") { collapsed.clear(); render(); }
      else if (act === "collapse") {
        defaults();                               // stacks stay stacked when a collection is reopened
        walk(model, n => { if (n.kind === "collection") collapsed.add(n.key); });
        render();
      }
      else if (act === "in") { userZoom = true; scale = Math.min(2, scale * 1.2); render(); }
      else if (act === "out") { userZoom = true; scale = Math.max(0.25, scale / 1.2); render(); }
      else if (act === "fit") { userZoom = false; render(); }
    });
    bar.querySelector("[data-act=group]").addEventListener("change", ev => { grouping = ev.target.checked; defaults(); render(); });
  })();

  model = build(data, "0");
  defaults();
  render();
  window.addEventListener("resize", () => { if (!userZoom) render(); });
})();
