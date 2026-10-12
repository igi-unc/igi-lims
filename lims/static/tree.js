// Renders a provenance tree as SVG. Input: window.TREE (nested {sample, children}), window.HIGHLIGHT.
(function () {
  const data = window.TREE, highlight = window.HIGHLIGHT || "";
  const svg = document.getElementById("tree-svg");
  if (!svg || !data) return;
  const NODE_W = 150, NODE_H = 40, GAP_X = 60, GAP_Y = 12;
  const nodes = [], links = [];
  let leafCounter = 0;
  function layout(node, depth, parent) {
    const s = node.sample;
    const n = { s: s, depth: depth, children: [], parent: parent };
    if (!node.children.length) { n.y = leafCounter++; }
    else {
      node.children.forEach(c => n.children.push(layout(c, depth + (s ? 1 : 0), n)));
      n.y = (n.children[0].y + n.children[n.children.length - 1].y) / 2;
    }
    if (s) { nodes.push(n); if (parent && parent.s) links.push([parent, n]); }
    return n;
  }
  layout(data, 0, null);
  const maxDepth = Math.max(...nodes.map(n => n.depth)), rows = Math.max(leafCounter, 1);
  const W = (maxDepth + 1) * (NODE_W + GAP_X), H = rows * (NODE_H + GAP_Y) + 20;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = Math.min(H, 2000) + "px";
  const x = n => n.depth * (NODE_W + GAP_X) + 10, y = n => n.y * (NODE_H + GAP_Y) + 10;
  const colors = { Available: "#dcfce7", Depleted: "#fee2e2", Shipped: "#dbeafe", Destroyed: "#e5e7eb", "In use": "#fef3c7" };
  let out = "";
  links.forEach(([a, b]) => {
    const x1 = x(a) + NODE_W, y1 = y(a) + NODE_H / 2, x2 = x(b), y2 = y(b) + NODE_H / 2;
    out += `<path d="M${x1},${y1} C${x1 + GAP_X / 2},${y1} ${x2 - GAP_X / 2},${y2} ${x2},${y2}" fill="none" stroke="#9ca3af" stroke-width="1.5"/>`;
  });
  nodes.forEach(n => {
    const s = n.s, parts = s.sample_id.split("-"), short = parts.slice(-3).join("-");
    const fill = s.deleted_at ? "#f3f4f6" : (colors[s.status] || "#fff");
    const stroke = s.sample_id === highlight ? "#1f5fbf" : "#9ca3af", sw = s.sample_id === highlight ? 3 : 1;
    out += `<a href="/samples/${s.sample_id}"><g transform="translate(${x(n)},${y(n)})">` +
      `<rect width="${NODE_W}" height="${NODE_H}" rx="5" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>` +
      `<text x="8" y="17" font-size="13" font-family="ui-monospace,Menlo,monospace" font-weight="600">${short}</text>` +
      `<text x="8" y="32" font-size="11" fill="#4b5563">${s.status}${s.quantity != null ? " · " + s.quantity + " " + (s.unit || "") : ""}</text>` +
      `<title>${s.sample_id}\n${s.status}${s.created_datetime ? "\n" + s.created_datetime : ""}${s.created_by ? " " + s.created_by : ""}</title>` +
      `</g></a>`;
  });
  svg.innerHTML = out;
})();
