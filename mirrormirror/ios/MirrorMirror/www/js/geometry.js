/* Plain geometry on {x, y} points. No dependencies, runs in the browser and in Node. */

export const PHI = (1 + Math.sqrt(5)) / 2; // 1.618033988749895

export const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
export const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
export const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
export const add = (a, b) => ({ x: a.x + b.x, y: a.y + b.y });
export const scale = (a, k) => ({ x: a.x * k, y: a.y * k });
export const dot = (a, b) => a.x * b.x + a.y * b.y;
export const len = (a) => Math.hypot(a.x, a.y);
export const unit = (a) => { const l = len(a) || 1; return { x: a.x / l, y: a.y / l }; };
export const perp = (a) => ({ x: -a.y, y: a.x });
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export const deg = (rad) => (rad * 180) / Math.PI;
export const rad = (d) => (d * Math.PI) / 180;

/** Mean of a list of numbers. */
export function mean(values) {
  if (!values.length) return NaN;
  let s = 0;
  for (const v of values) s += v;
  return s / values.length;
}

/** Median of a list of numbers (robust to a few bad frames). */
export function median(values) {
  if (!values.length) return NaN;
  const a = [...values].sort((p, q) => p - q);
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

/** Convert MediaPipe normalized landmarks ([0,1] relative to width/height) into pixel points.
 *  Measuring in pixels matters: a 3:4 frame would otherwise squash every horizontal distance. */
export function toPixels(landmarks, width, height) {
  const out = new Array(landmarks.length);
  for (let i = 0; i < landmarks.length; i++) {
    const l = landmarks[i];
    out[i] = { x: l.x * width, y: l.y * height, z: (l.z || 0) * width };
  }
  return out;
}

/** Median landmark set across several frames: per index, per coordinate. */
export function medianLandmarks(frames) {
  if (!frames.length) return [];
  const n = frames[0].length;
  const out = new Array(n);
  const xs = new Array(frames.length), ys = new Array(frames.length), zs = new Array(frames.length);
  for (let i = 0; i < n; i++) {
    for (let f = 0; f < frames.length; f++) { xs[f] = frames[f][i].x; ys[f] = frames[f][i].y; zs[f] = frames[f][i].z || 0; }
    out[i] = { x: median(xs), y: median(ys), z: median(zs) };
  }
  return out;
}

/** Least-squares line through points (principal axis). Returns {p: centroid, d: unit direction}. */
export function fitLine(points) {
  const n = points.length;
  const c = { x: mean(points.map((p) => p.x)), y: mean(points.map((p) => p.y)) };
  let sxx = 0, syy = 0, sxy = 0;
  for (const p of points) { const dx = p.x - c.x, dy = p.y - c.y; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; }
  // Principal eigenvector of the 2x2 covariance matrix.
  const theta = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  let d = { x: Math.cos(theta), y: Math.sin(theta) };
  if (d.y < 0) d = scale(d, -1); // point "down" the face, top to chin
  return { p: c, d, n };
}

/** Signed perpendicular distance from point q to line {p, d}. Positive on the side of perp(d). */
export function signedDistanceToLine(q, line) {
  return dot(sub(q, line.p), perp(line.d));
}

/** Scalar position of q along the line direction (0 at the centroid). */
export function alongLine(q, line) {
  return dot(sub(q, line.p), line.d);
}

/** Reflect point q across line {p, d}. */
export function reflectAcross(q, line) {
  const s = signedDistanceToLine(q, line);
  return sub(q, scale(perp(line.d), 2 * s));
}

/** Angle in degrees of the segment a->b measured from the horizontal axis (image coordinates, y down). */
export function segmentAngleDeg(a, b) {
  return deg(Math.atan2(b.y - a.y, b.x - a.x));
}

/** Round to n decimals (for display and tests). */
export function round(v, n = 3) {
  const k = 10 ** n;
  return Math.round(v * k) / k;
}
