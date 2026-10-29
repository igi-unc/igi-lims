// Print station: connects to a Brady printer with Brady's Web SDK (Web Bluetooth), then claims queued print jobs
// from the LIMS and prints them, one label image per tube (plus a header label per job).
const S = window.STATION;
const $ = id => document.getElementById(id);
const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
let sdk = null, busy = false;
const log = [];

function addLog(text, cls) {
  log.unshift(`<li class="${cls || ""}">${new Date().toLocaleTimeString()} · ${esc(text)}</li>`);
  $("st-log").innerHTML = log.slice(0, 30).join("");
}

function connected() { try { return !!(sdk && sdk.isConnected()); } catch (e) { return false; } }

function showStatus() {
  const rows = [];
  if (sdk && connected()) {
    const p = (k, label) => { if (sdk[k] !== undefined && sdk[k] !== null && sdk[k] !== "") rows.push(`<tr><th>${label}</th><td>${esc(sdk[k])}</td></tr>`); };
    p("printerName", "Printer"); p("status", "Status"); p("supplyName", "Labels loaded"); p("supplyDimensions", "Label size");
    p("dotsPerInch", "Resolution (dpi)"); p("batteryLevelPercentage", "Battery %"); p("ribbonRemainingPercent", "Ribbon left %");
    p("supplyRemainingPercentage", "Labels left %"); p("message", "Message"); p("messageRemedy", "Remedy");
  }
  $("st-status").innerHTML = rows.length ? rows.join("") :
    `<tr><td class="muted">${sdk ? "Disconnected. Click \"Connect printer\" again." : "Not connected. Click \"Connect printer\" and choose the M611 from the list (once per page load)."}</td></tr>`;
  $("st-test").disabled = !connected();
  // the loaded labels should be the stock the LIMS draws for
  const warn = $("st-warn");
  const dims = sdk && connected() ? String(sdk.supplyDimensions || "") : "";
  const name = sdk && connected() ? String(sdk.supplyName || "") : "";
  if (dims || name) {
    const want = [S.stock.width_in, S.stock.height_in].map(Number);
    const nums = (dims.match(/[\d.]+/g) || []).map(Number);
    const sizeOk = nums.length < 2 || want.every(w => nums.some(n => Math.abs(n - w) < 0.06));
    const partOk = !name || name.toUpperCase().includes(S.stock.part.toUpperCase());
    warn.hidden = sizeOk || partOk;
    warn.textContent = `The printer reports ${name || "labels"} ${dims}; the LIMS draws for ${S.stock.part} (${S.stock.width_in} x ${S.stock.height_in} in). Labels may be scaled.`;
  } else warn.hidden = true;
}

async function loadSdk() {
  if (sdk) return sdk;
  const mod = await import(S.sdkUrl);
  const BradySdk = mod.default;
  sdk = new BradySdk(() => showStatus(), false);
  if (sdk.isSupportedBrowser && !(await sdk.isSupportedBrowser())) {
    $("st-browser").textContent = "This browser cannot reach Bluetooth printers. Use Chrome or Edge on this computer.";
  }
  return sdk;
}

// Draw a same-origin SVG label into a pure black-and-white bitmap the size the printer expects.
async function bitmap(url) {
  const dpi = Number((sdk && sdk.dotsPerInch) || S.stock.dpi);
  const W = Math.round(S.stock.width_in * dpi), H = Math.round(S.stock.height_in * dpi);
  const svgImg = new Image();
  svgImg.src = url;
  await svgImg.decode();
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(svgImg, 0, 0, W, H);
  const d = ctx.getImageData(0, 0, W, H), px = d.data;
  for (let i = 0; i < px.length; i += 4) {           // thermal transfer prints black or nothing
    const v = (px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114) < 150 ? 0 : 255;
    px[i] = px[i + 1] = px[i + 2] = v; px[i + 3] = 255;
  }
  ctx.putImageData(d, 0, 0);
  const out = new Image();
  out.src = c.toDataURL("image/png");
  await out.decode();
  out.className = "label-preview";
  return out;
}

async function printImages(imgs) {
  const strip = $("st-preview");
  strip.innerHTML = "";
  imgs.forEach(i => strip.appendChild(i.cloneNode()));
  return imgs.length === 1 ? sdk.printBitmap(imgs[0]) : sdk.printBitmaps(imgs);
}

async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {}),
                              credentials: "same-origin"});
  if (r.redirected || r.status === 401 || r.status === 403) throw new Error("logged out");
  return r.json();
}

async function tick() {
  if (busy || !connected() || !$("st-auto").checked) return;
  busy = true;
  let job = null;
  try {
    const res = await post(S.claimUrl);
    $("st-queued").textContent = `(${res.queued || 0} waiting)`;
    job = res.job;
    if (!job) { $("st-current").textContent = "Idle."; return; }
    $("st-current").textContent = `Printing job #${job.id} for ${job.initials || job.requested_by}: ${job.n_labels} label(s)…`;
    const imgs = [];
    for (const im of job.images) imgs.push(await bitmap(im.url));
    const ok = await printImages(imgs);
    if (!ok) throw new Error((sdk.message || "the printer refused the job") + (sdk.messageRemedy ? " (" + sdk.messageRemedy + ")" : ""));
    await post(S.doneUrl.replace("/0/", `/${job.id}/`), {token: job.token, ok: true});
    addLog(`job #${job.id}: ${job.n_labels} label(s) for ${job.initials || job.requested_by}`, "");
    $("st-current").textContent = `Job #${job.id} printed.`;
  } catch (e) {
    if (job) {
      try { await post(S.doneUrl.replace("/0/", `/${job.id}/`), {token: job.token, ok: false, error: String(e.message || e)}); } catch (_) {}
      addLog(`job #${job.id} FAILED: ${e.message || e}. Requeue it from the print queue page once fixed.`, "error");
    } else addLog(`could not reach the LIMS: ${e.message || e}`, "error");
    $("st-current").textContent = "Stopped on an error; see below.";
  } finally { busy = false; }
}

$("st-connect").addEventListener("click", async () => {
  try {
    await loadSdk();
    const id = await sdk.showDiscoveredBleDevices(localStorage.getItem("bradyPrinterId") || undefined);
    if (id) localStorage.setItem("bradyPrinterId", id);
    if (!connected()) addLog("not connected: " + (sdk.getConnectionErrorMessage ? sdk.getConnectionErrorMessage() : "no printer chosen"), "error");
    else addLog(`connected to ${sdk.printerName || "printer"}`);
  } catch (e) {
    addLog("could not load Brady's printing library or connect: " + (e.message || e), "error");
  }
  showStatus();
});

$("st-test").addEventListener("click", async () => {
  try {
    const ok = await printImages([await bitmap(S.testUrl)]);
    addLog(ok ? "test label printed" : "test label failed: " + (sdk.message || ""), ok ? "" : "error");
  } catch (e) { addLog("test label failed: " + (e.message || e), "error"); }
});

const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
if (!navigator.bluetooth) $("st-browser").textContent = iOS
  ? "On an iPad, Safari and Chrome cannot reach Bluetooth printers. Open this page in the Bluefy browser (free in the App Store) instead."
  : "This browser has no Bluetooth support for web pages. Use Chrome or Edge.";
showStatus();
setInterval(tick, 4000);
