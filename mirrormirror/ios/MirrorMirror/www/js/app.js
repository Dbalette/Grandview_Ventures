/* Mirror Mirror on The Wall: camera, face landmarks, capture, verdict. */
import { analyze } from './phi.js';
import { toPixels, medianLandmarks, mean } from './geometry.js';
import { estimatePose, checkPose } from './pose.js';
import { drawPreview } from './overlay.js';
import { renderVerdict, composeCard } from './ui.js';
import { estimateHairline } from './hairline.js';
import { createPaywall, renderPaywall, PAYWALL } from './paywall.js';

const VISION_VERSION = '0.10.35'; // last release of @mediapipe/tasks-vision without usage telemetry
const CFG = window.MM_CONFIG || {}; // the iOS app injects this (bundled library, model, pricing); the web uses the defaults
const resolveUrl = (u) => new URL(u, document.baseURI).href.replace(/\/+$/, '');
const CDN_BASES = (Array.isArray(CFG.visionBases) && CFG.visionBases.length ? CFG.visionBases : [
  `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_VERSION}`,
  `https://unpkg.com/@mediapipe/tasks-vision@${VISION_VERSION}`,
]).map(resolveUrl);
const MODEL_URL = resolveUrl(CFG.modelUrl || 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task');
const CAPTURE_FRAMES = 24;        // about a second of video
const COUNTDOWN_SECONDS = 3;

const $ = (id) => document.getElementById(id);
const views = { welcome: $('view-welcome'), mirror: $('view-mirror'), verdict: $('view-verdict'), paywall: $('view-paywall'), error: $('view-error') };
const video = $('video'), overlay = $('overlay'), work = $('work');
const octx = overlay.getContext('2d');

const state = {
  landmarker: null, mode: 'VIDEO', stream: null, facing: 'user', running: false, rafId: 0,
  lastVideoTime: -1, lastTs: 0, capturing: null, lastResult: null, media: null, inflight: false,
};
const paywall = createPaywall();
state.paywall = paywall;
window.__mirror = state; // for tests and the curious

/* ----------------------------------------------------------------- helpers */
function showView(name) {
  for (const [k, v] of Object.entries(views)) v.hidden = k !== name;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function setStatus(text, kind = '') { const s = $('model-status'); s.textContent = text; s.className = `status ${kind}`; }
function setGuidance(text) { const g = $('guidance'); if (g.textContent !== text) g.textContent = text; }
function showError(text) { $('error-text').textContent = text; showView('error'); }
function updatePlanStatus() {
  const el = $('plan-status'); if (!el) return;
  el.innerHTML = '';
  if (paywall.isEntitled()) {
    el.append('Mirror Mirror Premium: unlimited readings.');
    if (paywall.hasStore) { const a = document.createElement('a'); a.href = '#'; a.textContent = 'Manage'; a.addEventListener('click', (e) => { e.preventDefault(); paywall.manage(); }); el.append(' ', a); }
    return;
  }
  const left = paywall.freeLeft();
  const b = document.createElement('b');
  b.textContent = left === 0 ? 'No free readings left' : `${left} free ${left === 1 ? 'reading' : 'readings'} left`;
  el.append(b, ` \u00b7 then ${paywall.state.price} a ${paywall.state.period} for unlimited readings.`);
}
function showPaywall() {
  stopCamera(); state.capturing = null; state.inflight = false;
  renderPaywall($('paywall-root'), paywall, {
    onBack: () => { updatePlanStatus(); showView('welcome'); },
    onUnlocked: () => { updatePlanStatus(); setStatus('Welcome to Mirror Mirror Premium. The glass is yours.', 'ok'); showView('welcome'); },
  });
  const h2 = $('paywall-root').querySelector('h2'); if (h2) h2.id = 'paywall-heading';
  showView('paywall');
}
const isAppleWebKit = () => /AppleWebKit/.test(navigator.userAgent) && /Safari|iPhone|iPad|Macintosh/.test(navigator.userAgent) && !/Chrome|CriOS|Edg/.test(navigator.userAgent);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ----------------------------------------------------------------- model */
let landmarkerReady = null;
function loadLandmarker() {
  if (landmarkerReady) return landmarkerReady;
  landmarkerReady = (async () => {
    let lastErr = null;
    for (const base of CDN_BASES) {
      try {
        setStatus('Polishing the glass… fetching the vision library');
        const mod = await import(`${base}/vision_bundle.mjs`);
        const fileset = await mod.FilesetResolver.forVisionTasks(`${base}/wasm`);
        setStatus('Teaching the mirror to see… loading the face model (3.8 MB)');
        const make = (delegate) => mod.FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate },
          runningMode: 'VIDEO', numFaces: 1,
          outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true,
          minFaceDetectionConfidence: 0.5, minFacePresenceConfidence: 0.5, minTrackingConfidence: 0.5,
        });
        let lm;
        try { lm = await make(isAppleWebKit() ? 'CPU' : 'GPU'); }
        catch (e) { console.warn('GPU delegate failed, using CPU', e); lm = await make('CPU'); }
        state.landmarker = lm; state.mode = 'VIDEO';
        setStatus('The mirror is ready. It never sends your face anywhere.', 'ok');
        return lm;
      } catch (e) { console.warn('vision library failed from', base, e); lastErr = e; }
    }
    setStatus('The mirror could not fetch its vision library. Check your connection and reload.', 'err');
    landmarkerReady = null;
    throw lastErr || new Error('vision library unavailable');
  })();
  return landmarkerReady;
}
async function ensureMode(mode) {
  if (state.mode !== mode) { await state.landmarker.setOptions({ runningMode: mode }); state.mode = mode; state.lastVideoTime = -1; }
}

/* ----------------------------------------------------------------- camera */
async function openMirror() {
  if (!paywall.canScan()) { showPaywall(); return; }
  showView('mirror');
  setGuidance('Asking for the camera…');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showError('This browser cannot open the camera here. The camera needs a secure (https) page and a modern browser. You can still use a photo instead.');
    return;
  }
  try {
    stopCamera();
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: state.facing, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false,
    });
  } catch (e) {
    const msg = e && e.name === 'NotAllowedError'
      ? 'The mirror needs the camera and was told no. Allow the camera for this page in your browser settings, or use a photo instead.'
      : e && e.name === 'NotFoundError' ? 'No camera could be found on this device. You can use a photo instead.'
      : `The camera could not be opened (${e && e.name ? e.name : 'unknown error'}). You can use a photo instead.`;
    showError(msg); return;
  }
  video.srcObject = state.stream;
  video.classList.toggle('unmirrored', state.facing !== 'user');
  try { await video.play(); } catch (e) { /* autoplay policies: the stream still renders once metadata arrives */ }
  for (let i = 0; i < 100 && !(video.videoWidth > 0); i++) await sleep(50);
  overlay.width = video.videoWidth || 640; overlay.height = video.videoHeight || 480;
  setGuidance('Waking the mirror…');
  try { await loadLandmarker(); } catch (e) { showError('The vision library could not be loaded, so the mirror cannot see. Check your connection and try again.'); return; }
  await ensureMode('VIDEO');
  state.running = true; state.lastVideoTime = -1;
  $('btn-consult').disabled = false;
  loop();
}
function stopCamera() {
  state.running = false;
  if (state.rafId) cancelAnimationFrame(state.rafId);
  if (state.stream) { for (const t of state.stream.getTracks()) t.stop(); state.stream = null; }
  video.srcObject = null;
  octx.clearRect(0, 0, overlay.width, overlay.height);
}

function expressionFrom(res) {
  const cats = res.faceBlendshapes && res.faceBlendshapes[0] && res.faceBlendshapes[0].categories;
  if (!cats) return null;
  const g = (name) => { const c = cats.find((x) => x.categoryName === name); return c ? c.score : 0; };
  return { smile: Math.max(g('mouthSmileLeft'), g('mouthSmileRight')), jawOpen: g('jawOpen'), blink: Math.max(g('eyeBlinkLeft'), g('eyeBlinkRight')), browUp: g('browInnerUp'), pucker: g('mouthPucker') };
}
function expressionHint(e) {
  if (!e) return null;
  if (e.smile > 0.35) return 'Lovely smile. Now relax it for the reading';
  if (e.jawOpen > 0.2) return 'Close your lips gently';
  if (e.pucker > 0.5) return 'Relax your lips';
  if (e.browUp > 0.5) return 'Relax your eyebrows';
  return null;
}

function loop() {
  if (!state.running) return;
  if (video.readyState >= 2 && video.currentTime !== state.lastVideoTime) {
    state.lastVideoTime = video.currentTime;
    const ts = Math.max(performance.now(), state.lastTs + 1); state.lastTs = ts;
    let res = null;
    try { res = state.landmarker.detectForVideo(video, ts); } catch (e) { console.warn(e); }
    handleFrame(res);
  }
  state.rafId = requestAnimationFrame(loop);
}

function setDots(checks) {
  for (const k of ['face', 'yaw', 'pitch', 'roll', 'size']) $(`dot-${k}`).classList.toggle('on', !!(checks && checks[k]));
}

function handleFrame(res) {
  const W = overlay.width, H = overlay.height;
  const mirror = state.facing === 'user';
  if (!res || !res.faceLandmarks || !res.faceLandmarks.length) {
    drawPreview(octx, null, W, H, { mirror });
    setDots(null); setGuidance('Looking for a face…'); $('mirror-frame').classList.remove('good');
    return;
  }
  const px = toPixels(res.faceLandmarks[0], W, H);
  const matrix = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0] ? res.facialTransformationMatrixes[0].data : null;
  const pose = estimatePose(px, matrix);
  const check = checkPose(pose, px, W, H);
  const expr = expressionFrom(res);
  const good = check.ok && !expressionHint(expr);
  drawPreview(octx, px, W, H, { mirror, good });
  setDots(check.checks);
  $('mirror-frame').classList.toggle('good', good);
  if (state.capturing) {
    const c = state.capturing;
    c.frames.push(px); c.poses.push(pose); c.exprs.push(expr); c.fracs.push(check.faceFrac);
    if (!c.snapshot && c.frames.length >= Math.floor(CAPTURE_FRAMES / 2)) c.snapshot = snapshotVideo();
    setGuidance(`Reading… ${Math.min(100, Math.round((c.frames.length / CAPTURE_FRAMES) * 100))}%`);
    if (c.frames.length >= CAPTURE_FRAMES) finishCapture();
    return;
  }
  setGuidance(check.ok ? (expressionHint(expr) || 'Perfect. Hold still and consult the mirror') : check.hint);
}

function snapshotVideo() {
  const c = document.createElement('canvas');
  c.width = video.videoWidth; c.height = video.videoHeight;
  c.getContext('2d').drawImage(video, 0, 0);
  return c;
}

/* ----------------------------------------------------------------- capture */
async function consult() {
  if (!state.running || state.capturing || state.inflight) return;
  if (!paywall.canScan()) { showPaywall(); return; }
  state.inflight = true;
  $('btn-consult').disabled = true;
  const cd = $('countdown');
  for (let n = COUNTDOWN_SECONDS; n >= 1; n--) {
    cd.textContent = String(n); cd.classList.remove('tick'); void cd.offsetWidth; cd.classList.add('tick');
    setGuidance(n === COUNTDOWN_SECONDS ? 'Chin level, eyes to the glass…' : 'Hold still…');
    await sleep(1000);
    if (!state.running) { cd.textContent = ''; state.inflight = false; return; }
  }
  cd.textContent = '';
  state.capturing = { frames: [], poses: [], exprs: [], fracs: [], snapshot: null };
}

async function finishCapture() {
  const c = state.capturing; state.capturing = null;
  const snapshot = c.snapshot || snapshotVideo();
  stopCamera();
  const px = medianLandmarks(c.frames);
  const pose = { yaw: mean(c.poses.map((p) => p.yaw)), pitch: mean(c.poses.map((p) => p.pitch)), roll: mean(c.poses.map((p) => p.roll)) };
  const exprs = c.exprs.filter(Boolean);
  const expression = exprs.length ? { smile: mean(exprs.map((e) => e.smile)), jawOpen: mean(exprs.map((e) => e.jawOpen)), blink: mean(exprs.map((e) => e.blink)), browUp: mean(exprs.map((e) => e.browUp)) } : null;
  await presentVerdict(snapshot, px, { pose, expression, source: 'camera', frames: c.frames.length, faceFrac: mean(c.fracs) }, state.facing === 'user');
  state.inflight = false;
}

/* ----------------------------------------------------------------- photo */
async function analyzePhoto(file) {
  if (!file || state.inflight) return;
  if (!paywall.canScan()) { showPaywall(); return; }
  state.inflight = true;
  setStatus('Reading your photograph…');
  try {
    const bitmap = await decodeImage(file);
    const maxEdge = 1600;
    const s = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * s); canvas.height = Math.round(bitmap.height * s);
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if (bitmap.close) bitmap.close();
    await loadLandmarker();
    await ensureMode('IMAGE');
    const res = state.landmarker.detect(canvas);
    if (!res.faceLandmarks || !res.faceLandmarks.length) {
      showError('The mirror could not find a face in that photograph. Try a brighter, closer, straight-on picture.');
      return;
    }
    const px = toPixels(res.faceLandmarks[0], canvas.width, canvas.height);
    const matrix = res.facialTransformationMatrixes && res.facialTransformationMatrixes[0] ? res.facialTransformationMatrixes[0].data : null;
    const pose = estimatePose(px, matrix);
    const check = checkPose(pose, px, canvas.width, canvas.height);
    const expression = expressionFrom(res);
    await presentVerdict(canvas, px, { pose, expression, source: 'photo', frames: 1, faceFrac: check.faceFrac }, false);
  } catch (e) {
    console.error(e);
    showError('That photograph could not be read. Try a JPEG or PNG taken straight on.');
  } finally {
    state.inflight = false;
    setStatus(state.landmarker ? 'The mirror is ready. It never sends your face anywhere.' : '', state.landmarker ? 'ok' : '');
  }
}
async function decodeImage(file) {
  try { return await createImageBitmap(file, { imageOrientation: 'from-image' }); }
  catch (e) {
    const url = URL.createObjectURL(file);
    try {
      const img = new Image(); img.src = url; await img.decode();
      return img;
    } finally { setTimeout(() => URL.revokeObjectURL(url), 10000); }
  }
}

/* ----------------------------------------------------------------- verdict */
async function presentVerdict(image, px, ctx, mirror) {
  const width = image.width || image.naturalWidth, height = image.height || image.naturalHeight;
  // Hairline search on a modest copy of the frame.
  let hairline = null;
  try {
    const s = Math.min(1, 720 / Math.max(width, height));
    const c = document.createElement('canvas'); c.width = Math.round(width * s); c.height = Math.round(height * s);
    const cx = c.getContext('2d', { willReadFrequently: true }); cx.drawImage(image, 0, 0, c.width, c.height);
    const img = cx.getImageData(0, 0, c.width, c.height);
    const small = px.map((q) => ({ x: q.x * s, y: q.y * s }));
    const pre = analyze(small, {});
    const h = estimateHairline(img, small, pre.measurements.axis, pre.measurements.faceLength, pre.measurements.faceWidth);
    hairline = h.found ? { found: true, point: { x: h.point.x / s, y: h.point.y / s }, pxAbove: h.pxAbove / s, lanes: h.lanes } : { found: false, lanes: h.lanes };
  } catch (e) { console.warn('hairline search failed', e); }

  const result = analyze(px, { ...ctx, hairline });
  state.lastResult = result;
  state.media = { image, width, height, landmarks: px, mirror };
  renderVerdict($('verdict-root'), result, state.media);
  showView('verdict');
  paywall.recordScan();
  updatePlanStatus();
}

async function saveCard() {
  if (!state.lastResult) return;
  try { await document.fonts.ready; } catch (e) { /* fine */ }
  const canvas = composeCard(state.lastResult, state.media);
  const blob = await new Promise((r) => canvas.toBlob(r, 'image/png'));
  const file = new File([blob], `mirror-mirror-${state.lastResult.scoreRounded}.png`, { type: 'image/png' });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: 'Mirror Mirror on The Wall', text: `The mirror says ${state.lastResult.scoreRounded} out of 100: ${state.lastResult.tier.label}.` }); return; }
    catch (e) { if (e && e.name === 'AbortError') return; }
  }
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = file.name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/* ----------------------------------------------------------------- wiring */
function init() {
  $('btn-open').addEventListener('click', () => openMirror());
  $('file-input').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; e.target.value = ''; analyzePhoto(f); });
  $('btn-consult').addEventListener('click', () => consult());
  $('btn-flip').addEventListener('click', async () => { state.facing = state.facing === 'user' ? 'environment' : 'user'; await openMirror(); });
  $('btn-cancel').addEventListener('click', () => { stopCamera(); state.capturing = null; state.inflight = false; showView('welcome'); });
  $('btn-again').addEventListener('click', () => { showView('welcome'); });
  $('btn-save').addEventListener('click', () => saveCard());
  $('btn-error-back').addEventListener('click', () => { stopCamera(); showView('welcome'); });
  document.addEventListener('visibilitychange', () => { if (document.hidden && state.running) { stopCamera(); showView('welcome'); } });

  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    navigator.serviceWorker.register('sw.js').catch((e) => console.warn('service worker not registered', e));
  }
  paywall.onChange(updatePlanStatus);
  updatePlanStatus();
  paywall.refresh();
  // Begin fetching the model while the visitor reads the instructions.
  loadLandmarker().catch(() => {});
}
init();
