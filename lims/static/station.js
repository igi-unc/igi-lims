// Print station. Two ways to reach the printer:
//   windows   - the Brady driver on this computer (USB). Each job is laid out as label-sized pages and printed with
//               window.print(); Chrome started with --kiosk-printing sends it to the default printer without a dialog.
//   bluetooth - Brady's Web SDK over Web Bluetooth (Chrome/Edge on a computer or Android tablet).
// Either way the station claims queued jobs from the LIMS in order and reports each one printed or failed.
const S = window.STATION;
const $ = id => document.getElementById(id);
const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;");
let mode = localStorage.getItem("stationMode") || "windows";
let sdk = null, busy = false, windowsRunning = false;
const log = [];

function addLog(text, cls) {
  log.unshift(`<li class="${cls || ""}">${new Date().toLocaleTimeString()} · ${esc(text)}</li>`);
  $("st-log").innerHTML = log.slice(0, 30).join("");
}

// ---------------------------------------------------------------- mode switch
function setMode(m) {
  mode = m; localStorage.setItem("stationMode", m);
  $("pane-windows").hidden = m !== "windows";
  $("pane-bluetooth").hidden = m !== "bluetooth";
  $("mode-windows").classList.toggle("active", m === "windows");
  $("mode-bluetooth").classList.toggle("active", m === "bluetooth");
  showStatus();
}
document.querySelectorAll("[data-mode]").forEach(a => a.addEventListener("click", e => { e.preventDefault(); setMode(a.dataset.mode); }));

function ready() { return mode === "windows" ? windowsRunning : btConnected(); }

// ---------------------------------------------------------------- Windows printer (driver + kiosk printing)
// Brady's M611 driver lays an upright 0.5 x 1 in page onto the 1 x 0.5 in label, so the label image is printed on an
// upright page turned a quarter turn left ("portrait", calibration LAYOUT C, confirmed on the printer). The other
// layouts remain for other printers or drivers; Calibrate prints all four to choose from.
// the layout a person chose on this station, else the site default (LABEL_PRINT_LAYOUT; "portrait" = calibration C)
let orient = localStorage.getItem("stationLayoutChoice") || S.defaultLayout || "portrait";
const LAYOUTS = ["landscape", "landscape-flip", "portrait", "portrait-right"];
// Every layout is a CSS named page, so one print can mix them (the calibration print). The chosen layout is also the
// default @page for printers or browsers that ignore named pages.
function layoutRules(o) {
  const W = S.stock.width_in, H = S.stock.height_in, upright = o.startsWith("portrait");
  const pw = upright ? H : W, ph = upright ? W : H;
  let img = `width:${W}in;height:${H}in;`;
  if (o === "landscape-flip") img += `position:absolute;left:0;top:0;transform-origin:50% 50%;transform:rotate(180deg);`;
  if (o === "portrait") img += `position:absolute;left:0;top:0;transform-origin:0 0;transform:translateY(${W}in) rotate(-90deg);`;
  if (o === "portrait-right") img += `position:absolute;left:0;top:0;transform-origin:0 0;transform:translateX(${H}in) rotate(90deg);`;
  return {pw, ph, img};
}
function pageCss(current) {
  const cur = layoutRules(current);
  let css = `@media print { @page { size: ${cur.pw}in ${cur.ph}in; margin: 0; }\n`;
  for (const o of LAYOUTS) {
    const r = layoutRules(o);
    css += `  @page lay-${o} { size: ${r.pw}in ${r.ph}in; margin: 0; }
  #print-area .pl.lay-${o} { page: lay-${o}; width:${r.pw}in; height:calc(${r.ph}in - 0.005in); }
  #print-area .pl.lay-${o} img { ${r.img} }\n`;
  }
  return css + "}";
}
function applyOrient(o) {
  orient = o;
  let st = document.getElementById("print-page-style");
  if (!st) { st = document.createElement("style"); st.id = "print-page-style"; document.head.appendChild(st); }
  st.textContent = pageCss(o);
  $("st-orient").value = o;

}
$("st-orient").addEventListener("change", e => {
  localStorage.setItem("stationLayoutChoice", e.target.value);
  applyOrient(e.target.value); addLog("page layout: " + e.target.selectedOptions[0].text);
});
applyOrient(orient);
function loadImg(url) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("could not load " + url)); i.src = url; });
}

// pages: list of URLs, or of [url, layout] pairs; queue jobs (checkDialog) stop the station if a print dialog appeared
async function printWindows(pages, checkDialog = false) {
  const area = $("print-area");
  area.innerHTML = "";
  const items = pages.map(p => Array.isArray(p) ? p : [p, orient]);
  const imgs = await Promise.all(items.map(([u]) => loadImg(u)));     // all labels loaded before printing
  imgs.forEach((img, i) => { const d = document.createElement("div"); d.className = "pl lay-" + items[i][1]; d.appendChild(img); area.appendChild(d); });
  showPreview(items.map(([u]) => u));
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const t0 = performance.now();
  window.print();                                             // with --kiosk-printing: straight to the default printer
  const waited = performance.now() - t0;
  area.innerHTML = "";
  if (checkDialog && waited > 2500) {                         // a print dialog was open: not in silent-printing mode
    stopWindows("A print dialog appeared, so Chrome is not in silent-printing mode (start it from the --kiosk-printing shortcut). Printing stopped.");
    throw new Error("print dialog shown instead of silent printing; check whether the labels came out before requeueing");
  }
  return true;
}

$("st-start").addEventListener("click", () => {
  windowsRunning = !windowsRunning;
  $("st-start").textContent = windowsRunning ? "Stop printing" : "Start printing";
  addLog(windowsRunning ? "printing through the Windows printer" : "stopped");
  showStatus();
});
$("st-wcal").addEventListener("click", async () => {
  const pages = [["landscape", "A"], ["landscape-flip", "B"], ["portrait", "C"], ["portrait-right", "D"]]
    .map(([o, tag]) => [S.alignUrl + "?tag=" + tag, o]);
  try { await printWindows(pages); addLog("calibration: printed LAYOUT A to D as one 4-page print; choose the one that came out right"); }
  catch (e) { addLog("calibration failed: " + (e.message || e), "error"); }
});
$("st-walign").addEventListener("click", async () => {
  try { await printWindows([S.alignUrl]); addLog("alignment label sent to the Windows printer"); }
  catch (e) { addLog("alignment label failed: " + (e.message || e), "error"); }
});
$("st-wtest").addEventListener("click", async () => {
  try { await printWindows([S.testUrl]); addLog("test label sent to the Windows printer"); }
  catch (e) { addLog("test label failed: " + (e.message || e), "error"); }
});
// a station that was printing through Windows starts again by itself after a restart (Startup-folder shortcut);
// a browser that never pressed Start never prints on its own
if (mode === "windows" && localStorage.getItem("stationAutostart") === "1") { windowsRunning = true; $("st-start").textContent = "Stop printing"; }
$("st-start").addEventListener("click", () => localStorage.setItem("stationAutostart", windowsRunning ? "1" : "0"));
function stopWindows(reason) {
  windowsRunning = false; localStorage.setItem("stationAutostart", "0");
  $("st-start").textContent = "Start printing";
  addLog(reason, "error");
}

// ---------------------------------------------------------------- Bluetooth (Brady Web SDK)
function btConnected() { try { return !!(sdk && sdk.isConnected()); } catch (e) { return false; } }

function showStatus() {
  const rows = [];
  if (sdk && btConnected()) {
    const p = (k, label) => { if (sdk[k] !== undefined && sdk[k] !== null && sdk[k] !== "") rows.push(`<tr><th>${label}</th><td>${esc(sdk[k])}</td></tr>`); };
    p("printerName", "Printer"); p("status", "Status"); p("supplyName", "Labels loaded"); p("supplyDimensions", "Label size");
    p("dotsPerInch", "Resolution (dpi)"); p("batteryLevelPercentage", "Battery %"); p("ribbonRemainingPercent", "Ribbon left %");
    p("supplyRemainingPercentage", "Labels left %"); p("message", "Message"); p("messageRemedy", "Remedy");
  }
  $("st-status").innerHTML = rows.length ? rows.join("") :
    `<tr><td class="muted">${sdk ? "Disconnected. Click \"Connect printer\" again." : "Not connected. Click \"Connect printer\" and choose the M611 from the list (once per page load)."}</td></tr>`;
  $("st-test").disabled = !btConnected();
  const warn = $("st-warn");
  const dims = sdk && btConnected() ? String(sdk.supplyDimensions || "") : "";
  const name = sdk && btConnected() ? String(sdk.supplyName || "") : "";
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
  sdk = new mod.default(() => showStatus(), false);
  if (sdk.isSupportedBrowser && !(await sdk.isSupportedBrowser()))
    $("st-browser").textContent = "This browser cannot reach Bluetooth printers. Use Chrome or Edge, or the Windows printer mode.";
  return sdk;
}

// same-origin SVG label -> pure black-and-white bitmap the size the printer expects
async function bitmap(url) {
  const dpi = Number((sdk && sdk.dotsPerInch) || S.stock.dpi);
  const W = Math.round(S.stock.width_in * dpi), H = Math.round(S.stock.height_in * dpi);
  const svgImg = await loadImg(url);
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(svgImg, 0, 0, W, H);
  const d = ctx.getImageData(0, 0, W, H), px = d.data;
  for (let i = 0; i < px.length; i += 4) {
    const v = (px[i] * 0.299 + px[i + 1] * 0.587 + px[i + 2] * 0.114) < 150 ? 0 : 255;
    px[i] = px[i + 1] = px[i + 2] = v; px[i + 3] = 255;
  }
  ctx.putImageData(d, 0, 0);
  return loadImg(c.toDataURL("image/png"));
}

async function printBluetooth(urls) {
  const imgs = [];
  for (const u of urls) imgs.push(await bitmap(u));
  showPreview(urls);
  const ok = imgs.length === 1 ? await sdk.printBitmap(imgs[0]) : await sdk.printBitmaps(imgs);
  if (!ok) throw new Error((sdk.message || "the printer refused the job") + (sdk.messageRemedy ? " (" + sdk.messageRemedy + ")" : ""));
  return true;
}

$("st-connect").addEventListener("click", async () => {
  try {
    await loadSdk();
    const id = await sdk.showDiscoveredBleDevices(localStorage.getItem("bradyPrinterId") || undefined);
    if (id) localStorage.setItem("bradyPrinterId", id);
    if (!btConnected()) addLog("not connected: " + (sdk.getConnectionErrorMessage ? sdk.getConnectionErrorMessage() : "no printer chosen"), "error");
    else addLog(`connected to ${sdk.printerName || "printer"}`);
  } catch (e) { addLog("could not load Brady's printing library or connect: " + (e.message || e), "error"); }
  showStatus();
});
$("st-test").addEventListener("click", async () => {
  try { await printBluetooth([S.testUrl]); addLog("test label printed"); }
  catch (e) { addLog("test label failed: " + (e.message || e), "error"); }
});

// ---------------------------------------------------------------- the queue
function showPreview(urls) {
  const strip = $("st-preview");
  strip.innerHTML = urls.map(u => `<img class="label-preview" src="${esc(u)}" alt="">`).join("");
}

async function post(url, body) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {}),
                              credentials: "same-origin"});
  if (r.redirected || r.status === 401 || r.status === 403) throw new Error("logged out");
  return r.json();
}

async function tick() {
  if (busy || !ready() || !$("st-auto").checked) return;
  busy = true;
  let job = null;
  try {
    const res = await post(S.claimUrl);
    $("st-queued").textContent = `(${res.queued || 0} waiting)`;
    job = res.job;
    if (!job) { $("st-current").textContent = "Idle."; return; }
    $("st-current").textContent = `Printing job #${job.id} for ${job.initials || job.requested_by}: ${job.n_labels} label(s)…`;
    const urls = job.images.map(i => i.url);
    if (mode === "windows") await printWindows(urls, true); else await printBluetooth(urls);
    await post(S.doneUrl.replace("/0/", `/${job.id}/`), {token: job.token, ok: true});
    addLog(`job #${job.id}: ${job.n_labels} label(s) for ${job.initials || job.requested_by}`);
    $("st-current").textContent = `Job #${job.id} printed.`;
  } catch (e) {
    if (job) {
      try { await post(S.doneUrl.replace("/0/", `/${job.id}/`), {token: job.token, ok: false, error: String(e.message || e)}); } catch (_) {}
      addLog(`job #${job.id} FAILED: ${e.message || e}. Requeue it from the print queue page once fixed.`, "error");
    } else addLog(`could not reach the LIMS: ${e.message || e}`, "error");
    $("st-current").textContent = "Stopped on an error; see below.";
  } finally { busy = false; }
}

const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
if (!navigator.bluetooth) $("st-browser").textContent = iOS
  ? "On an iPad, Safari and Chrome cannot reach Bluetooth printers."
  : "This browser has no Bluetooth support for web pages. Use Chrome or Edge, or the Windows printer mode.";
setMode(mode);
setInterval(tick, 4000);
