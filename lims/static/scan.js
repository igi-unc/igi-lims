// Camera scanning of tube labels (Data Matrix holding the sample ID). Uses the browser's own BarcodeDetector when it
// reads Data Matrix (Chrome on Android, macOS, ChromeOS), otherwise a pinned WebAssembly ponyfill (Safari on iPad and
// iPhone, Chrome/Edge on Windows). A recognised ID opens the tube page; anything else is shown, not followed.
const C = window.SCAN;
const $ = id => document.getElementById(id);
const idRe = new RegExp(C.pattern);
const video = $("sc-video");
let detector = null, stream = null, timer = null, last = "", lastAt = 0;

const status = (t, cls) => { $("sc-status").textContent = t; $("sc-status").className = cls || "muted"; };

async function getDetector() {
  if ("BarcodeDetector" in window) {
    try {
      const formats = await window.BarcodeDetector.getSupportedFormats();
      if (formats.includes("data_matrix")) return new window.BarcodeDetector({formats: ["data_matrix", "qr_code"]});
    } catch (e) { /* fall through to the ponyfill */ }
  }
  const mod = await import(C.readerUrl);
  return new mod.BarcodeDetector({formats: ["data_matrix", "qr_code"]});
}

async function listCameras() {
  try {
    const cams = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
    const sel = $("sc-camera");
    if (cams.length > 1) {
      sel.innerHTML = cams.map((c, i) => `<option value="${c.deviceId}">${c.label || "camera " + (i + 1)}</option>`).join("");
      const cur = stream && stream.getVideoTracks()[0].getSettings().deviceId;
      if (cur) sel.value = cur;
      sel.hidden = false;
    }
  } catch (e) { /* labels need permission first; ignore */ }
}

async function start(deviceId) {
  stop();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    status("This browser cannot use the camera here (it needs a secure https page). Type the ID below instead.", "error");
    return;
  }
  try {
    status("Starting the camera…");
    stream = await navigator.mediaDevices.getUserMedia({audio: false, video: deviceId ? {deviceId: {exact: deviceId}}
      : {facingMode: {ideal: "environment"}, width: {ideal: 1280}, height: {ideal: 720}}});
    video.srcObject = stream;
    await video.play();
    $("sc-start").hidden = true;
    listCameras();
    if (!detector) { status("Loading the code reader…"); detector = await getDetector(); }
    status("Hold the label inside the frame, about 10 cm from the camera.");
    timer = setInterval(scanFrame, 200);
  } catch (e) {
    $("sc-start").hidden = false;
    status(e.name === "NotAllowedError" ? "Camera permission was refused. Allow the camera for this site, then press Start camera."
                                        : "Could not start the camera: " + (e.message || e), "error");
  }
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  if (stream) stream.getTracks().forEach(t => t.stop());
  stream = null;
}

let busy = false;
async function scanFrame() {
  if (busy || !detector || video.readyState < 2) return;
  busy = true;
  try {
    const codes = await detector.detect(video);
    for (const c of codes) found((c.rawValue || "").trim().toUpperCase());
  } catch (e) { /* a bad frame; try the next one */ }
  finally { busy = false; }
}

function found(value) {
  if (!value) return;
  const now = Date.now();
  if (value === last && now - lastAt < 3000) return;          // the same label held in view
  last = value; lastAt = now;
  if (navigator.vibrate) navigator.vibrate(60);
  if (!idRe.test(value)) {
    status(`Read "${value}", which is not an IGI tube ID.`, "error");
    return;
  }
  const url = C.sampleUrl.replace("__ID__", encodeURIComponent(value));
  if ($("sc-stay").checked) {
    const li = document.createElement("li");
    li.innerHTML = `<a href="${url}"><code></code></a> <span class="muted">${new Date().toLocaleTimeString()}</span>`;
    li.querySelector("code").textContent = value;
    $("sc-list").prepend(li);
    status(`Read ${value}. Keep scanning.`);
  } else {
    stop();
    status(`Read ${value}. Opening…`);
    window.location.href = url;
  }
}

$("sc-start").addEventListener("click", () => start());
$("sc-camera").addEventListener("change", e => start(e.target.value));
$("sc-stay").addEventListener("change", e => localStorage.setItem("scanStay", e.target.checked ? "1" : "0"));
$("sc-stay").checked = localStorage.getItem("scanStay") === "1";
window.addEventListener("pagehide", stop);
window.addEventListener("pageshow", e => { if (e.persisted) start(); });   // back from a tube page
start();
