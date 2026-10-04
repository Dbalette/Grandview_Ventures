import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { analyze, scoreAgainst, symmetryScore, tierFor, scoreDistances, PHI, WEIGHTS } from '../js/phi.js';
import { toPixels, medianLandmarks, round } from '../js/geometry.js';
import { referenceDistances, REFERENCE_ASYMMETRY_PERCENT } from '../js/norms.js';
import { poseFromMatrix, poseFromLandmarks, checkPose } from '../js/pose.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const fx = JSON.parse(fs.readFileSync(path.join(here, 'fixtures', 'face-neutral.json'), 'utf8'));
const norm = fx.landmarks.map(([x, y, z]) => ({ x, y, z }));
const px = toPixels(norm, fx.width, fx.height);

test('scoring rule: each percent of deviation costs one point', () => {
  assert.equal(scoreAgainst(PHI, PHI), 100);
  assert.equal(round(scoreAgainst(PHI * 1.1, PHI), 6), 90);
  assert.equal(round(scoreAgainst(PHI * 0.9, PHI), 6), 90);
  assert.equal(scoreAgainst(PHI * 3, PHI), 0);
  assert.equal(scoreAgainst(NaN, PHI), 0);
});

test('symmetry rule: 2.5 points per percent of asymmetry', () => {
  assert.equal(symmetryScore(0), 100);
  assert.equal(symmetryScore(4), 90);
  assert.equal(symmetryScore(60), 0);
});

test('tiers are contiguous and ordered', () => {
  assert.equal(tierFor(100).label, 'Fairest of them all');
  assert.equal(tierFor(95).label, 'Fairest of them all');
  assert.equal(tierFor(94.9).label, 'A face for the golden age');
  assert.equal(tierFor(0).label, 'Beyond the formula');
});

test('a perfectly golden set of distances scores 100', () => {
  const g = PHI;
  const d = {
    faceLength: 100 * g, faceWidth: 100, mouthWidth: 50 * g, noseWidth: 50, noseLength: 50 * g,
    outerEyeSpan: 50 * g * g, innerEyeSpan: 50, eyeWidth: 50, interpupillary: 46,
    glabellaToSubnasale: 60, subnasaleToMenton: 60, eyesToStomion: 40 * g * g, alarToStomion: 40, noseTipToMenton: 40 * g * g,
    stomionToMenton: 40 * g, subnasaleToStomion: 20 * g,
  };
  const r = scoreDistances(d, 0);
  assert.equal(round(r.phiScore, 6), 100);
  assert.equal(round(r.score, 6), 100);
});

test('the real fixture face produces a complete, plausible verdict', () => {
  const a = analyze(px, { source: 'photo' });
  assert.equal(a.groups.phi.metrics.length, 7);
  assert.equal(a.groups.canons.metrics.length, 6);
  assert.equal(a.groups.modern.metrics.length, 2);
  assert.ok(a.score > 70 && a.score < 100, `score ${a.score}`);
  for (const m of a.allMetrics) {
    assert.ok(isFinite(m.measured) && m.measured > 0, m.id);
    assert.ok(m.score >= 0 && m.score <= 100, m.id);
    assert.ok(m.segments.length >= 2, `${m.id} has drawable segments`);
    assert.ok(m.formula && m.explain && m.source, `${m.id} is documented`);
  }
  assert.ok(a.symmetry.index >= 0 && a.symmetry.index < 10, `asymmetry ${a.symmetry.index}`);
  assert.ok(a.mmPerPx > 0.05 && a.mmPerPx < 1, `mm per px ${a.mmPerPx}`);
  const faceLengthMm = a.measurements.faceLength * a.mmPerPx;
  assert.ok(faceLengthMm > 120 && faceLengthMm < 220, `face length ${faceLengthMm} mm`);
  assert.equal(round(a.score, 6), round(WEIGHTS.phi * a.groups.phi.score + WEIGHTS.symmetry * a.symmetry.score, 6));
  assert.ok(a.verdict.includes(a.tier.line));
});

test('the verdict is invariant to mirroring, scale and translation', () => {
  const base = analyze(px, {});
  const mirrored = analyze(px.map((q) => ({ x: fx.width - q.x, y: q.y, z: q.z })), {});
  const scaled = analyze(px.map((q) => ({ x: q.x * 2.5 + 40, y: q.y * 2.5 + 7, z: q.z * 2.5 })), {});
  assert.equal(round(mirrored.score, 6), round(base.score, 6));
  assert.equal(round(scaled.score, 6), round(base.score, 6));
  assert.equal(round(mirrored.symmetry.index, 6), round(base.symmetry.index, 6));
  for (let i = 0; i < base.allMetrics.length; i++) {
    assert.equal(round(scaled.allMetrics[i].measured, 6), round(base.allMetrics[i].measured, 6), base.allMetrics[i].id);
  }
});

test('a rolled head changes the verdict very little (distances follow the facial axis)', () => {
  const base = analyze(px, {});
  const cx = fx.width / 2, cy = fx.height / 2, a = (12 * Math.PI) / 180;
  const rolled = analyze(px.map((q) => ({ x: cx + (q.x - cx) * Math.cos(a) - (q.y - cy) * Math.sin(a), y: cy + (q.x - cx) * Math.sin(a) + (q.y - cy) * Math.cos(a), z: q.z })), {});
  assert.ok(Math.abs(rolled.score - base.score) < 0.05, `${rolled.score} vs ${base.score}`);
});

test('median landmarks steady a jittery capture', () => {
  const frames = [];
  for (let f = 0; f < 9; f++) frames.push(px.map((q) => ({ x: q.x + (f % 2 ? 1 : -1) * 0.7, y: q.y + (f % 3 === 0 ? 2 : 0), z: q.z })));
  frames.push(px.map((q) => ({ x: q.x + 25, y: q.y - 25, z: q.z }))); // one bad frame
  const med = medianLandmarks(frames);
  assert.ok(Math.abs(med[1].x - px[1].x) <= 0.7 && Math.abs(med[1].y - px[1].y) <= 2);
});

test('the Farkas average faces land in the low nineties under the mirror rules', () => {
  for (const k of ['female', 'male']) {
    const r = scoreDistances(referenceDistances(k), REFERENCE_ASYMMETRY_PERCENT);
    assert.ok(r.score > 88 && r.score < 96, `${k} ${r.score}`);
  }
});

test('head pose from the fixture matrix is near frontal and agrees in sign with the landmarks', () => {
  const m = poseFromMatrix(fx.matrix);
  const l = poseFromLandmarks(px);
  assert.ok(Math.abs(m.yaw) < 5 && Math.abs(m.pitch) < 8 && Math.abs(m.roll) < 5, JSON.stringify(m));
  assert.ok(Math.abs(l.yaw) < 8, JSON.stringify(l));
  const c = checkPose(m, px, fx.width, fx.height);
  assert.equal(c.ok, true, c.hint);
  // a turned matrix: rotate the forward axis 20 degrees about Y
  const t = 20 * Math.PI / 180;
  const turned = [Math.cos(t), 0, -Math.sin(t), 0, 0, 1, 0, 0, Math.sin(t), 0, Math.cos(t), 0, 0, 0, -60, 1];
  assert.ok(Math.abs(poseFromMatrix(turned).yaw - 20) < 0.01);
  const c2 = checkPose(poseFromMatrix(turned), px, fx.width, fx.height);
  assert.equal(c2.checks.yaw, false);
  assert.match(c2.hint, /Turn a touch/);
});
