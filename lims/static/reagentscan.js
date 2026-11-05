// "Scan kit / reagent" on the registration forms: read a kit or reagent box's code (camera, USB scanner or typed),
// ask the LIMS what it is, and fill the kit and lot fields of the metadata below. Unknown products are learned once.
(function () {
  const C = window.RGSCAN, $ = id => document.getElementById(id);
  const bar = $("rg-bar"), dlg = $("rg-dialog"), video = $("rg-video"), out = $("rg-result");
  if (!C || !bar || !dlg) return;
  const box = $("attr-fields");
  const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  const sel = f => box.querySelector(`select[name="attr_${f}"]`);
  const presentFields = () => Object.keys(C.fields).filter(f => sel(f));
  const status = (t, cls) => { $("rg-status").textContent = t; $("rg-status").className = "small " + (cls || "muted"); };
  let detector = null, stream = null, timer = null, busy = false, lastText = "";

  function refreshBar() { bar.hidden = presentFields().length === 0; }
  document.addEventListener("attrs-rendered", refreshBar);
  refreshBar();

  async function getDetector() {
    const formats = ["data_matrix", "qr_code", "code_128", "gs1_databar"];
    if ("BarcodeDetector" in window) {
      try {
        const have = await window.BarcodeDetector.getSupportedFormats();
        if (have.includes("data_matrix")) return new window.BarcodeDetector({formats: formats.filter(f => have.includes(f))});
      } catch (e) { /* use the ponyfill */ }
    }
    const mod = await import(C.readerUrl);
    return new mod.BarcodeDetector({formats: ["data_matrix", "qr_code", "code_128"]});
  }
  async function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { status("No camera here (needs https). Use a USB scanner or type the code."); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: false, video: {facingMode: {ideal: "environment"}, width: {ideal: 1280}, height: {ideal: 720}}});
      video.srcObject = stream; await video.play();
      if (!detector) { status("Loading the code reader…"); detector = await getDetector(); }
      status("Hold the box's 2D code inside the frame.");
      timer = setInterval(scanFrame, 200);
    } catch (e) {
      status(e.name === "NotAllowedError" ? "Camera permission was refused; use a USB scanner or type the code." : "Camera unavailable: " + (e.message || e));
    }
  }
  function stopCamera() {
    if (timer) clearInterval(timer); timer = null;
    if (stream) stream.getTracks().forEach(t => t.stop()); stream = null;
  }
  async function scanFrame() {
    if (busy || !detector || video.readyState < 2) return;
    busy = true;
    try { const codes = await detector.detect(video); if (codes.length) handle((codes[0].rawValue || "").trim()); }
    catch (e) { /* next frame */ } finally { busy = false; }
  }

  async function post(url, body) {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, credentials: "same-origin", body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  function choose(field, code, meaning) {
    const s = sel(field); if (!s) return false;
    if (![...s.options].some(o => o.value === code)) {
      const o = document.createElement("option"); o.value = code; o.textContent = meaning ? `${code} – ${meaning}` : code; s.appendChild(o);
    }
    s.value = code; s.dispatchEvent(new Event("change", {bubbles: true}));
    s.classList.add("rg-filled"); setTimeout(() => s.classList.remove("rg-filled"), 2500);
    return true;
  }
  const labelOf = f => { const s = sel(f); const l = s && s.closest("label"); return l ? l.querySelector(".lbl").textContent.replace(" *", "") : f; };

  async function handle(text) {
    if (!text || text === lastText) return;
    lastText = text;
    status("Looking it up…");
    try { render(await post(C.lookup, {text, fields: presentFields()})); }
    catch (e) { status("Lookup failed: " + e.message, "error"); lastText = ""; }
  }
  function render(r) {
    const filled = [];
    r.matches.forEach(m => { if (choose(m.field, m.code, m.meaning)) filled.push(`${labelOf(m.field)} = ${m.code}`); });
    let html = `<p class="small">Scanned <code class="wrap">${esc(r.raw)}</code>${r.gs1 ? "" : ' <span class="muted">(not a GS1 code)</span>'}</p>`;
    if (r.gs1) html += `<p class="small">Product <code>${esc(r.product_key || "–")}</code>` + (r.lot ? ` · lot <code>${esc(r.lot)}</code>` : "") +
                       (r.expiry ? ` · expires ${esc(r.expiry)}` : "") + (r.gtin_valid === false ? ` <span class="error">(check digit wrong)</span>` : "") + `</p>`;
    if (r.expired) html += `<p class="flash warn">This box expired on ${esc(r.expiry)}. Check before using it.</p>`;
    // lots: select it, or offer to add it to the list
    (r.lots || []).forEach(l => {
      if (!sel(l.field)) return;
      if (l.exists) { if (choose(l.field, r.lot)) filled.push(`${labelOf(l.field)} = ${r.lot}`); }
      else if (l.addable && r.matches.length) html += `<p><button type="button" class="small" data-addlot="${esc(l.field)}">Add lot ${esc(r.lot)} to “${esc(labelOf(l.field))}” and select it</button></p>`;
    });
    if (!r.matches.length && r.product_key) {
      const fields = presentFields();
      html += `<p class="small"><b>New product.</b> Which entry is it? The LIMS remembers the answer for the next scan.</p>` +
        `<p><select id="rg-field">${fields.map(f => `<option value="${esc(f)}">${esc(labelOf(f))}</option>`).join("")}</select> ` +
        `<select id="rg-code"></select> <button type="button" class="small" id="rg-learn">Remember and fill</button></p>`;
    }
    if (filled.length) html += `<p class="flash ok">Filled: ${filled.map(esc).join(", ")}.</p>`;
    out.innerHTML = html;
    if (filled.length) $("rg-msg").textContent = "Filled from the scan: " + filled.join(", ") + ".";
    status(filled.length ? "Done. Scan another box or close." : "Scanned.");
    const fsel = $("rg-field");
    if (fsel) {
      const fillCodes = () => {
        const src = sel(fsel.value);
        $("rg-code").innerHTML = [...src.options].filter(o => o.value).map(o => `<option value="${esc(o.value)}">${esc(o.textContent)}</option>`).join("");
      };
      fsel.addEventListener("change", fillCodes); fillCodes();
      $("rg-learn").addEventListener("click", async () => {
        try {
          await post(C.remember, {product_key: r.product_key, field: fsel.value, code: $("rg-code").value});
          lastText = ""; handle(r.raw);
        } catch (e) { status("Could not save: " + e.message, "error"); }
      });
    }
    out.querySelectorAll("button[data-addlot]").forEach(b => b.addEventListener("click", async () => {
      const m = r.matches[0];
      try {
        const res = await post(C.lot, {field: b.dataset.addlot, lot: r.lot,
                                       meaning: `${m.meaning || m.code} lot ${r.lot}` + (r.expiry ? `, expires ${r.expiry}` : "")});
        choose(res.field, res.code, res.meaning);
        b.replaceWith(Object.assign(document.createElement("p"), {className: "flash ok", textContent: `Added and selected lot ${r.lot}.`}));
        $("rg-msg").textContent += ` Lot ${r.lot} added.`;
      } catch (e) { status("Could not add the lot: " + e.message, "error"); }
    }));
  }

  $("rg-open").addEventListener("click", () => {
    out.innerHTML = ""; lastText = ""; $("rg-text").value = "";
    dlg.showModal(); startCamera(); setTimeout(() => $("rg-text").focus(), 50);
  });
  $("rg-text").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); lastText = ""; handle(e.target.value.trim()); } });
  const close = () => { stopCamera(); if (dlg.open) dlg.close(); };
  $("rg-close").addEventListener("click", close);
  dlg.addEventListener("close", stopCamera);
})();
