// Provenance tree as SVG. Input: window.TREE (nested {sample, children}; a top node with sample=null is a
// virtual root, e.g. a participant), window.HIGHLIGHT, optional window.MEANINGS and window.ROLE.
// Hover shows a tooltip; click pins a detail panel (if #tree-tip / #tree-panel exist).
(function () {
  const data = window.TREE, highlight = window.HIGHLIGHT || "", M = window.MEANINGS || {};
  const svg = document.getElementById("tree-svg"), tip = document.getElementById("tree-tip"), panel = document.getElementById("tree-panel");
  if (!svg || !data) return;
  const NODE_W = 112, NODE_H = 26, GAP_X = 44, GAP_Y = 8, PAD = 10;
  const nodes = [], links = [];
  let leafCounter = 0;
  function layout(node, depth, parent) {
    const n = { s: node.sample, label: node.sample ? null : (node.participant || "root"), depth, children: [], parent };
    if (!node.children.length) n.y = leafCounter++;
    else {
      node.children.forEach(c => n.children.push(layout(c, depth + 1, n)));
      n.y = (n.children[0].y + n.children[n.children.length - 1].y) / 2;
    }
    nodes.push(n);
    if (parent) links.push([parent, n]);
    return n;
  }
  layout(data, 0, null);
  const maxDepth = Math.max(...nodes.map(n => n.depth)), rows = Math.max(leafCounter, 1);
  const W = (maxDepth + 1) * (NODE_W + GAP_X) + PAD, H = rows * (NODE_H + GAP_Y) + 2 * PAD;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = Math.min(Math.max(H, 120), 1600) + "px";
  const x = n => n.depth * (NODE_W + GAP_X) + PAD, y = n => n.y * (NODE_H + GAP_Y) + PAD;
  const colors = { Available: "#dcfce7", Depleted: "#fee2e2", Shipped: "#dbeafe", Destroyed: "#e5e7eb", "In use": "#fef3c7" };
  const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  let out = "";
  links.forEach(([a, b]) => {
    const x1 = x(a) + NODE_W, y1 = y(a) + NODE_H / 2, x2 = x(b), y2 = y(b) + NODE_H / 2;
    out += `<path d="M${x1},${y1} C${x1 + GAP_X / 2},${y1} ${x2 - GAP_X / 2},${y2} ${x2},${y2}" fill="none" stroke="#9ca3af" stroke-width="1.3"/>`;
  });
  nodes.forEach((n, i) => {
    const s = n.s;
    let fill, stroke = "#9ca3af", sw = 1, text, sub = "";
    if (!s) { fill = "#1f5fbf"; text = n.label; }
    else {
      const parts = s.sample_id.split("-");
      // root tubes show date+specimen so collections are distinguishable; derived tubes show fraction-material-aliquot
      text = s.parent_id ? parts.slice(-3).join("-") : parts.slice(3, 5).join("-") + " " + parts.slice(-3).join("-");
      fill = s.deleted_at ? "#f3f4f6" : (colors[s.status] || "#fff");
      if (s.sample_id === highlight) { stroke = "#1f5fbf"; sw = 2.5; }
    }
    out += `<g class="node" data-i="${i}" transform="translate(${x(n)},${y(n)})" style="cursor:${s ? "pointer" : "default"}">` +
      `<rect width="${NODE_W}" height="${NODE_H}" rx="4" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>` +
      `<text x="6" y="17" font-size="${s && !s.parent_id ? 10 : 11.5}" font-family="ui-monospace,Menlo,monospace" font-weight="600" fill="${s ? "#1d2330" : "#fff"}">${esc(text)}</text></g>`;
  });
  svg.innerHTML = out;

  const meaning = (cat, code) => (M[cat] && M[cat][code]) ? `${code} – ${M[cat][code]}` : code;
  const loc = s => [s.freezer, s.rack, s.box, s.position].filter(v => v && v !== "NA").join(" / ") || "—";
  function summary(s) {
    return `<div class="t"><code>${esc(s.sample_id)}</code></div>` +
      `<div><span class="status ${esc(s.status)}">${esc(s.status)}</span>${s.deleted_at ? " <b>deleted</b>" : ""}</div>` +
      `<div>${esc(meaning("fraction", s.fraction_code))}</div><div>${esc(meaning("material", s.material_code))}</div>` +
      `<div>${s.quantity != null ? esc(s.quantity) + " " + esc(s.unit || "") : "—"} · ${esc(loc(s))}</div>` +
      `<div class="muted">${esc(s.created_datetime || "")} ${esc(s.created_by || "")}${s.sop_code ? " · " + esc(s.sop_code) : ""}</div>`;
  }
  function detail(s) {
    const rows = [["Specimen", meaning("specimen", s.specimen_code)], ["Fraction", meaning("fraction", s.fraction_code)],
      ["Material", meaning("material", s.material_code)], ["Collected", s.collection_date], ["Parent", s.parent_id || "none (root)"],
      ["Status", s.status], ["Quantity", s.quantity != null ? s.quantity + " " + (s.unit || "") : ""], ["Location", loc(s)],
      ["Processed", (s.created_datetime || "") + " " + (s.created_by || "") + (s.sop_code ? " · " + s.sop_code : "")],
      ["Biobank", meaning("biobank_source", s.biobank_source)], ["Notes", s.notes || ""]];
    return `<div class="t"><code>${esc(s.sample_id)}</code> <span class="status ${esc(s.status)}">${esc(s.status)}</span></div>` +
      `<table class="compact">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${esc(v)}</td></tr>`).join("")}</table>` +
      `<p><a class="btn secondary" href="/samples/${s.sample_id}">Open tube page</a> ` +
      (window.ROLE && window.ROLE !== "viewer" && !s.deleted_at ? `<a class="btn" href="/samples/${s.sample_id}/derive">Derive from this</a>` : "") +
      ` <button type="button" class="small secondary" id="tree-panel-close">close</button></p>`;
  }
  let pinned = null;
  svg.querySelectorAll("g.node").forEach(g => {
    const n = nodes[+g.dataset.i];
    if (!n.s) return;
    g.addEventListener("mousemove", ev => {
      if (!tip) return;
      tip.innerHTML = summary(n.s); tip.hidden = false;
      const r = svg.parentElement.getBoundingClientRect();
      tip.style.left = (ev.clientX - r.left + 14) + "px"; tip.style.top = (ev.clientY - r.top + 14) + "px";
    });
    g.addEventListener("mouseleave", () => { if (tip) tip.hidden = true; });
    g.addEventListener("click", () => {
      if (!panel) { window.location = "/samples/" + n.s.sample_id; return; }
      pinned = n.s; panel.innerHTML = detail(n.s); panel.hidden = false;
      document.getElementById("tree-panel-close").onclick = () => { panel.hidden = true; pinned = null; };
    });
  });
})();
