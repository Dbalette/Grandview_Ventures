/* Finding the hairline.
   The face mesh stops on the upper forehead, so the mirror walks up the facial axis from that point,
   comparing the colour of each strip of pixels with the forehead skin, until skin gives way to hair,
   a hat, or the background. Three parallel walks vote; the search is capped so a bald scalp or a
   receding hairline falls back to the mesh point rather than running to the top of the head. */
import { add, scale, perp, median } from './geometry.js';
import { LM } from './landmarks.js';

const DEFAULTS = {
  maxUpFrac: 0.26,        // search at most this fraction of the face length above the mesh top
  stripHalfWidthFrac: 0.05, // half-width of each sampled strip, as a fraction of face width
  laneOffsetFrac: 0.09,   // offset of the two side lanes, as a fraction of face width
  lumThreshold: 0.26,     // relative luminance change counted as "not skin"
  chromaThreshold: 0.040, // chromaticity (r/(r+g+b), g/(r+g+b)) distance counted as "not skin"
  persistence: 6,         // consecutive non-skin samples needed to call it a hairline
  step: 1,
};

function sampleStrip(img, cx, cy, dir, halfWidth) {
  // Median colour of pixels along a short line centred at (cx, cy) in direction `dir` (unit vector).
  const { width, height, data } = img;
  const rs = [], gs = [], bs = [];
  for (let s = -halfWidth; s <= halfWidth; s += 1) {
    const x = Math.round(cx + dir.x * s), y = Math.round(cy + dir.y * s);
    if (x < 0 || y < 0 || x >= width || y >= height) return null;
    const i = (y * width + x) * 4;
    rs.push(data[i]); gs.push(data[i + 1]); bs.push(data[i + 2]);
  }
  return { r: median(rs), g: median(gs), b: median(bs) };
}

function features(c) {
  const sum = c.r + c.g + c.b || 1;
  return { lum: (0.299 * c.r + 0.587 * c.g + 0.114 * c.b), rn: c.r / sum, gn: c.g / sum };
}

function differs(f, ref, o) {
  const dl = Math.abs(f.lum - ref.lum) / Math.max(ref.lum, 20);
  const dc = Math.hypot(f.rn - ref.rn, f.gn - ref.gn);
  return dl > o.lumThreshold || dc > o.chromaThreshold;
}

/**
 * @param {ImageData} img      the frame (any scale)
 * @param {Array} p            478 landmarks in the same pixel space as `img`
 * @param {{p:{x,y}, d:{x,y}}} axis  facial axis from phi.measure() (d points forehead -> chin)
 * @param {number} faceLength  pixels
 * @param {number} faceWidth   pixels
 * @returns {{found:boolean, point:{x,y}|null, pxAbove:number, lanes:number}}
 */
export function estimateHairline(img, p, axis, faceLength, faceWidth, options = {}) {
  const o = { ...DEFAULTS, ...options };
  const up = scale(axis.d, -1);              // towards the hairline
  const side = perp(axis.d);                 // across the face
  const top = p[LM.FOREHEAD_TOP];
  const glabella = p[LM.GLABELLA];
  const halfWidth = Math.max(3, Math.round(o.stripHalfWidthFrac * faceWidth));

  // Skin reference: the middle of the forehead, between the brow point and the mesh top.
  const refCentre = { x: (glabella.x + top.x) / 2, y: (glabella.y + top.y) / 2 };
  const refSamples = [];
  for (let dy = -3; dy <= 3; dy++) {
    const c = sampleStrip(img, refCentre.x + up.x * dy * 2, refCentre.y + up.y * dy * 2, side, halfWidth * 2);
    if (c) refSamples.push(c);
  }
  if (refSamples.length < 3) return { found: false, point: null, pxAbove: 0, lanes: 0 };
  const skin0 = { r: median(refSamples.map((c) => c.r)), g: median(refSamples.map((c) => c.g)), b: median(refSamples.map((c) => c.b)) };

  const maxUp = Math.round(o.maxUpFrac * faceLength);
  const lanes = [0, -o.laneOffsetFrac * faceWidth, o.laneOffsetFrac * faceWidth];
  const hits = [];
  for (const off of lanes) {
    const start = add(top, scale(side, off));
    let ref = features(skin0);
    let run = 0, hit = -1;
    for (let t = 0; t <= maxUp; t += o.step) {
      const c = sampleStrip(img, start.x + up.x * t, start.y + up.y * t, side, halfWidth);
      if (!c) { hit = -1; break; }          // ran off the image: this lane cannot vote
      const f = features(c);
      if (differs(f, ref, o)) {
        run += 1;
        if (run >= o.persistence) { hit = t - o.persistence + 1; break; }
      } else {
        run = 0;
        // Let the reference drift slowly with the forehead's shading so a gradual gradient does not trigger.
        ref = { lum: ref.lum * 0.92 + f.lum * 0.08, rn: ref.rn * 0.92 + f.rn * 0.08, gn: ref.gn * 0.92 + f.gn * 0.08 };
      }
    }
    if (hit >= 0) hits.push(hit);
  }
  if (hits.length < 2) return { found: false, point: null, pxAbove: 0, lanes: hits.length };
  const pxAbove = median(hits);
  return { found: true, point: add(top, scale(up, pxAbove)), pxAbove, lanes: hits.length };
}
