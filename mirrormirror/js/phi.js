/* The arithmetic of the mirror.
   Pure functions: landmarks in pixel coordinates in, a fully itemised verdict out.
   Nothing here touches the DOM, so the same code runs in the browser and in the Node tests. */
import { PHI, dist, mid, fitLine, signedDistanceToLine, alongLine, add, scale, perp, mean, clamp, round } from './geometry.js';
import { LM, MIDLINE, PAIRS } from './landmarks.js';

export { PHI };

/** Horizontal diameter of the adult iris, which varies remarkably little from person to person (MediaPipe iris docs). */
export const IRIS_DIAMETER_MM = 11.7;

/** Approximate millimetres per pixel from the two irises. */
export function irisScale(p) {
  const diam = (ring) => { const xs = ring.map((i) => p[i].x), ys = ring.map((i) => p[i].y); return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)); };
  const px = (diam(LM.IRIS_R_RING) + diam(LM.IRIS_L_RING)) / 2;
  return px > 0 ? IRIS_DIAMETER_MM / px : NaN;
}

/** Every sub-score uses the same rule: a reading that is off its ideal by d percent scores 100 - d.
 *  score = 100 x (1 - |measured - ideal| / ideal), floored at 0. */
export function scoreAgainst(measured, ideal) {
  if (!isFinite(measured) || !isFinite(ideal) || ideal === 0) return 0;
  return clamp(100 * (1 - Math.abs(measured - ideal) / ideal), 0, 100);
}

/** Symmetry: each 1% of average left-right asymmetry costs 2.5 points. */
export const SYMMETRY_POINTS_PER_PERCENT = 2.5;
export function symmetryScore(asymmetryPercent) {
  return clamp(100 - SYMMETRY_POINTS_PER_PERCENT * asymmetryPercent, 0, 100);
}

/** Headline weights. */
export const WEIGHTS = { phi: 0.8, symmetry: 0.2 };

export const COLORS = {
  faceLW: '#ffd166', mouthNose: '#ef476f', eyesMouth: '#06d6a0', lipsChin: '#4cc9f0', noseTipChin: '#f78c6b',
  eyesLips: '#c77dff', noseLW: '#8ecae6',
  thirds: '#ffe8a3', fifths: '#b5e48c', noseEyes: '#f4a261', mouthNoseCanon: '#e76f51', faceNose: '#90be6d', lipsCanon: '#a8dadc',
  pallettV: '#ffffff', pallettH: '#f1faee',
};

/* ------------------------------------------------------------------ measurements */

/** Build the named measurements from 478 pixel landmarks.
 *  `top` may override the forehead point (for example an estimated hairline). */
export function measure(p, { top = null } = {}) {
  const P = (i) => p[i];
  const axis = fitLine(MIDLINE.map(P));
  // Facial axis: unit vector d points from forehead to chin; perp(d) points to the subject's left (image right).
  const along = (q) => alongLine(q, axis);
  const across = (q) => signedDistanceToLine(q, axis);
  const onAxis = (t, offset = 0) => add(add(axis.p, scale(axis.d, t)), scale(perp(axis.d), offset));

  const topPt = top || P(LM.FOREHEAD_TOP);
  const menton = P(LM.MENTON);
  const stomion = mid(P(LM.STOMION_UPPER), P(LM.STOMION_LOWER));
  const pupilR = P(LM.IRIS_R), pupilL = P(LM.IRIS_L);
  const alarR = P(LM.ALAR_R), alarL = P(LM.ALAR_L);

  // Levels: positions along the facial axis (pixels from the axis centroid, increasing towards the chin).
  const lv = {
    top: along(topPt),
    glabella: along(P(LM.GLABELLA)),
    nasion: along(P(LM.NASION)),
    eyes: (along(pupilR) + along(pupilL)) / 2,
    noseTip: along(P(LM.NOSE_TIP)),
    alar: (along(alarR) + along(alarL)) / 2,
    subnasale: along(P(LM.SUBNASALE)),
    stomion: along(stomion),
    labraleInf: along(P(LM.LABRALE_INF)),
    menton: along(menton),
  };

  const eyeWidthR = dist(P(LM.EXOCANTHION_R), P(LM.ENDOCANTHION_R));
  const eyeWidthL = dist(P(LM.EXOCANTHION_L), P(LM.ENDOCANTHION_L));

  const m = {
    axis, levels: lv, onAxis, along, across, mmPerPx: irisScale(p),
    points: { top: topPt, menton, stomion, pupilR, pupilL, alarR, alarL },
    // Horizontal (straight-line) distances
    faceLength: dist(topPt, menton),
    faceWidth: dist(P(LM.ZYGION_R), P(LM.ZYGION_L)),
    jawWidth: dist(P(LM.GONION_R), P(LM.GONION_L)),
    mouthWidth: dist(P(LM.CHEILION_R), P(LM.CHEILION_L)),
    noseWidth: dist(alarR, alarL),
    noseLength: dist(P(LM.NASION), P(LM.SUBNASALE)),
    outerEyeSpan: dist(P(LM.EXOCANTHION_R), P(LM.EXOCANTHION_L)),
    innerEyeSpan: dist(P(LM.ENDOCANTHION_R), P(LM.ENDOCANTHION_L)),
    eyeWidthR, eyeWidthL, eyeWidth: (eyeWidthR + eyeWidthL) / 2,
    interpupillary: dist(pupilR, pupilL),
    // Vertical distances between levels, measured along the facial axis
    topToGlabella: lv.glabella - lv.top,
    glabellaToSubnasale: lv.subnasale - lv.glabella,
    subnasaleToMenton: lv.menton - lv.subnasale,
    eyesToStomion: lv.stomion - lv.eyes,
    eyesToAlar: lv.alar - lv.eyes,
    alarToStomion: lv.stomion - lv.alar,
    noseTipToMenton: lv.menton - lv.noseTip,
    subnasaleToStomion: lv.stomion - lv.subnasale,
    stomionToMenton: lv.menton - lv.stomion,
    topToMenton: lv.menton - lv.top,
  };
  return m;
}

/* ------------------------------------------------------------------ metric definitions */

/** A metric compares a measured ratio with an ideal. `num`/`den` name the two distances. */
function makeMetric(def, m, segments) {
  const measured = def.num.value / def.den.value;
  const deviation = (measured - def.ideal) / def.ideal; // signed, as a fraction
  return {
    id: def.id, group: def.group, name: def.name, formula: def.formula, explain: def.explain, source: def.source,
    num: def.num, den: def.den, measured, ideal: def.ideal, idealLabel: def.idealLabel,
    deviation, score: scoreAgainst(measured, def.ideal), weight: def.weight == null ? 1 : def.weight,
    color: COLORS[def.id] || '#ffffff', segments,
  };
}

/** Segment helpers: horizontal = between two landmarks; level = between two levels, drawn parallel to the axis at an offset. */
function segBetween(a, b, label) { return { a, b, label, px: dist(a, b) }; }
function segLevels(m, t1, t2, offsetFrac, label) {
  const off = offsetFrac * m.faceWidth;
  const a = m.onAxis(t1, off), b = m.onAxis(t2, off);
  return { a, b, label, px: Math.abs(t2 - t1) };
}

export function goldenMetrics(p, m) {
  const P = (i) => p[i];
  const L = m.levels;
  const list = [];

  list.push(makeMetric({
    id: 'faceLW', group: 'phi', name: 'Face length ÷ face width', ideal: PHI, idealLabel: 'φ',
    formula: '(top of forehead → chin) ÷ (cheek edge → cheek edge)',
    num: { label: 'face length', value: m.faceLength }, den: { label: 'face width', value: m.faceWidth },
    explain: 'The oldest claim of them all: the ideal face is a golden rectangle, 1.618 times as long as it is wide. Length runs from the top of the forehead to the bottom of the chin, width across the face at eye level, just in front of the ears.',
    source: 'Marquardt mask; popular lists; De Silva "face shape" marker',
  }, m, [segBetween(m.points.top, m.points.menton, 'face length'), segBetween(P(LM.ZYGION_R), P(LM.ZYGION_L), 'face width')]));

  list.push(makeMetric({
    id: 'mouthNose', group: 'phi', name: 'Mouth width ÷ nose width', ideal: PHI, idealLabel: 'φ',
    formula: '(mouth corner → mouth corner) ÷ (nostril edge → nostril edge)',
    num: { label: 'mouth width', value: m.mouthWidth }, den: { label: 'nose width', value: m.noseWidth },
    explain: 'Ricketts measured this with a golden divider in 1982: the mouth should be phi times as wide as the nose at its widest. A smile widens the mouth and spoils the reading, which is why the mirror asks for closed lips.',
    source: 'Ricketts 1982, Am J Orthod; popular lists',
  }, m, [segBetween(P(LM.CHEILION_R), P(LM.CHEILION_L), 'mouth width'), segBetween(P(LM.ALAR_R), P(LM.ALAR_L), 'nose width')]));

  list.push(makeMetric({
    id: 'eyesMouth', group: 'phi', name: 'Outer eye span ÷ mouth width', ideal: PHI, idealLabel: 'φ',
    formula: '(outer eye corner → outer eye corner) ÷ (mouth corner → mouth corner)',
    num: { label: 'outer eye span', value: m.outerEyeSpan }, den: { label: 'mouth width', value: m.mouthWidth },
    explain: 'The next step of Ricketts’ golden progression across the face: nose, then mouth, then the span of the eyes, each phi times the one before.',
    source: 'Ricketts 1982, Am J Orthod',
  }, m, [segBetween(P(LM.EXOCANTHION_R), P(LM.EXOCANTHION_L), 'outer eye span'), segBetween(P(LM.CHEILION_R), P(LM.CHEILION_L), 'mouth width')]));

  list.push(makeMetric({
    id: 'lipsChin', group: 'phi', name: 'Lips to chin ÷ nose base to lips', ideal: PHI, idealLabel: 'φ',
    formula: '(lip line → chin) ÷ (nostril level → lip line)',
    num: { label: 'lips to chin', value: m.stomionToMenton }, den: { label: 'nose base to lips', value: m.alarToStomion },
    explain: 'The lower face in golden section: from the line where the lips meet down to the chin should be phi times the distance from the base of the nose down to that same line.',
    source: 'Ricketts 1982 (stomion–menton : ala–stomion); popular "lips to chin : nose to lips"',
  }, m, [segLevels(m, L.stomion, L.menton, -0.22, 'lips to chin'), segLevels(m, L.alar, L.stomion, -0.22, 'nose base to lips')]));

  list.push(makeMetric({
    id: 'noseTipChin', group: 'phi', name: 'Nose tip to chin ÷ lips to chin', ideal: PHI, idealLabel: 'φ',
    formula: '(nose tip → chin) ÷ (lip line → chin)',
    num: { label: 'nose tip to chin', value: m.noseTipToMenton }, den: { label: 'lips to chin', value: m.stomionToMenton },
    explain: 'Another golden section of the lower face, this one anchored on the tip of the nose.',
    source: 'Popular golden-ratio face lists (PhiMatrix); De Silva "nose to chin"',
  }, m, [segLevels(m, L.noseTip, L.menton, 0.24, 'nose tip to chin'), segLevels(m, L.stomion, L.menton, 0.31, 'lips to chin')]));

  list.push(makeMetric({
    id: 'eyesLips', group: 'phi', name: 'Eyes to lips ÷ lips to chin', ideal: PHI, idealLabel: 'φ',
    formula: '(pupil level → lip line) ÷ (lip line → chin)',
    num: { label: 'eyes to lips', value: m.eyesToStomion }, den: { label: 'lips to chin', value: m.stomionToMenton },
    explain: 'Ricketts’ vertical proportion from the eyes: the drop from the pupils to the lip line, against the drop from the lip line to the chin.',
    source: 'Ricketts 1982 (stomion–eye : stomion–menton)',
  }, m, [segLevels(m, L.eyes, L.stomion, -0.34, 'eyes to lips'), segLevels(m, L.stomion, L.menton, -0.34, 'lips to chin')]));

  list.push(makeMetric({
    id: 'noseLW', group: 'phi', name: 'Nose length ÷ nose width', ideal: PHI, idealLabel: 'φ',
    formula: '(bridge → base of nose) ÷ (nostril edge → nostril edge)',
    num: { label: 'nose length', value: m.noseLength }, den: { label: 'nose width', value: m.noseWidth },
    explain: 'The nose as a golden rectangle: its length from the bridge between the eyes to the base, against its width across the nostrils.',
    source: 'Popular lists; De Silva "nose width and length" marker',
  }, m, [segBetween(P(LM.NASION), P(LM.SUBNASALE), 'nose length'), segBetween(P(LM.ALAR_R), P(LM.ALAR_L), 'nose width')]));

  return list;
}

export function canonMetrics(p, m) {
  const P = (i) => p[i];
  const L = m.levels;
  const list = [];

  list.push(makeMetric({
    id: 'thirds', group: 'canon', name: 'Middle third ÷ lower third', ideal: 1, idealLabel: '1 (equal thirds)',
    formula: '(brow line → base of nose) ÷ (base of nose → chin)',
    num: { label: 'middle third', value: m.glabellaToSubnasale }, den: { label: 'lower third', value: m.subnasaleToMenton },
    explain: 'Leonardo and the neoclassical sculptors divided the face into three equal storeys: hairline to brow, brow to nose base, nose base to chin. The mirror compares the two storeys it can see precisely; the top storey is shown for interest, since the mesh stops short of the hairline. Farkas found the three almost never equal in living faces, the lower third usually being the tallest.',
    source: 'Neoclassical canon; Farkas et al. 1985, Plast Reconstr Surg',
  }, m, [segLevels(m, L.glabella, L.subnasale, 0.38, 'middle third'), segLevels(m, L.subnasale, L.menton, 0.38, 'lower third'), segLevels(m, L.top, L.glabella, 0.38, 'top (to mesh edge)')]));

  list.push(makeMetric({
    id: 'fifths', group: 'canon', name: 'Outer eye span ÷ face width', ideal: 0.6, idealLabel: '0.6 (three fifths)',
    formula: '(outer eye corner → outer eye corner) ÷ (cheek edge → cheek edge)',
    num: { label: 'outer eye span', value: m.outerEyeSpan }, den: { label: 'face width', value: m.faceWidth },
    explain: 'The rule of fifths: the face is five eyes wide, and the two eyes with the gap between them fill the middle three fifths. So the span between the outer corners of the eyes should be 60% of the face width.',
    source: 'Neoclassical canon of facial fifths',
  }, m, [segBetween(P(LM.EXOCANTHION_R), P(LM.EXOCANTHION_L), 'outer eye span'), segBetween(P(LM.ZYGION_R), P(LM.ZYGION_L), 'face width')]));

  list.push(makeMetric({
    id: 'noseEyes', group: 'canon', name: 'Nose width ÷ distance between the eyes', ideal: 1, idealLabel: '1',
    formula: '(nostril edge → nostril edge) ÷ (inner eye corner → inner eye corner)',
    num: { label: 'nose width', value: m.noseWidth }, den: { label: 'inner eye gap', value: m.innerEyeSpan },
    explain: 'The orbitonasal canon: the nose is exactly as wide as the gap between the eyes. Of the nine canons Farkas tested, this one held most often, in 40% of young adults.',
    source: 'Neoclassical canon; Farkas et al. 1985',
  }, m, [segBetween(P(LM.ALAR_R), P(LM.ALAR_L), 'nose width'), segBetween(P(LM.ENDOCANTHION_R), P(LM.ENDOCANTHION_L), 'inner eye gap')]));

  list.push(makeMetric({
    id: 'mouthNoseCanon', group: 'canon', name: 'Mouth width ÷ nose width', ideal: 1.5, idealLabel: '1.5',
    formula: '(mouth corner → mouth corner) ÷ (nostril edge → nostril edge)',
    num: { label: 'mouth width', value: m.mouthWidth }, den: { label: 'nose width', value: m.noseWidth },
    explain: 'The naso-oral canon says one and a half, where the golden-ratio school says 1.618. Farkas measured young women at about 1.6 on average, so the two schools nearly agree.',
    source: 'Neoclassical canon; Farkas et al. 1985',
  }, m, [segBetween(P(LM.CHEILION_R), P(LM.CHEILION_L), 'mouth width'), segBetween(P(LM.ALAR_R), P(LM.ALAR_L), 'nose width')]));

  list.push(makeMetric({
    id: 'faceNose', group: 'canon', name: 'Face width ÷ nose width', ideal: 4, idealLabel: '4',
    formula: '(cheek edge → cheek edge) ÷ (nostril edge → nostril edge)',
    num: { label: 'face width', value: m.faceWidth }, den: { label: 'nose width', value: m.noseWidth },
    explain: 'The nasofacial canon: the nose is a quarter of the face’s width. Farkas found it true in 37% of faces, the second most reliable canon.',
    source: 'Neoclassical canon; Farkas et al. 1985',
  }, m, [segBetween(P(LM.ZYGION_R), P(LM.ZYGION_L), 'face width'), segBetween(P(LM.ALAR_R), P(LM.ALAR_L), 'nose width')]));

  list.push(makeMetric({
    id: 'lipsCanon', group: 'canon', name: 'Lips to chin ÷ nose to lips', ideal: 2, idealLabel: '2 (one third : two thirds)',
    formula: '(lip line → chin) ÷ (base of nose → lip line)',
    num: { label: 'lips to chin', value: m.stomionToMenton }, den: { label: 'nose to lips', value: m.subnasaleToStomion },
    explain: 'The aesthetic surgeons’ division of the lower face: the upper lip takes the top third, the lower lip and chin the remaining two thirds.',
    source: 'Powell & Humphreys 1984, Proportions of the Aesthetic Face',
  }, m, [segLevels(m, L.stomion, L.menton, -0.45, 'lips to chin'), segLevels(m, L.subnasale, L.stomion, -0.45, 'nose to lips')]));

  return list;
}

export function modernMetrics(p, m) {
  const P = (i) => p[i];
  const L = m.levels;
  return [
    makeMetric({
      id: 'pallettV', group: 'modern', name: 'Eyes to mouth ÷ face length', ideal: 0.36, idealLabel: '0.36',
      formula: '(pupil level → lip line) ÷ (top of forehead → chin)',
      num: { label: 'eyes to mouth', value: m.eyesToStomion }, den: { label: 'face length', value: m.faceLength },
      explain: 'Pallett, Link and Lee (2010) moved eyes and mouths around on otherwise identical faces and asked people which they preferred. The favourite put the mouth 36% of the face length below the eyes, which is simply where the average woman’s mouth is. Since the mesh stops a little below the hairline, readings here run a touch high.',
      source: 'Pallett, Link & Lee 2010, Vision Research',
    }, m, [segLevels(m, L.eyes, L.stomion, 0.44, 'eyes to mouth'), segBetween(m.points.top, m.points.menton, 'face length')]),
    makeMetric({
      id: 'pallettH', group: 'modern', name: 'Pupil distance ÷ face width', ideal: 0.46, idealLabel: '0.46',
      formula: '(pupil → pupil) ÷ (cheek edge → cheek edge)',
      num: { label: 'pupil distance', value: m.interpupillary }, den: { label: 'face width', value: m.faceWidth },
      explain: 'The same study’s horizontal finding: the preferred eyes sit 46% of the face width apart, measured between the inner edges of the ears, which is where the mesh takes its width.',
      source: 'Pallett, Link & Lee 2010, Vision Research',
    }, m, [segBetween(m.points.pupilR, m.points.pupilL, 'pupil distance'), segBetween(P(LM.ZYGION_R), P(LM.ZYGION_L), 'face width')]),
  ];
}

/* ------------------------------------------------------------------ symmetry */

/** Left-right symmetry about the fitted facial axis. */
export function symmetry(p, m) {
  const axis = m.axis;
  const rows = [];
  for (const [ri, li, label] of PAIRS) {
    const r = p[ri], l = p[li];
    const dR = Math.abs(signedDistanceToLine(r, axis)), dL = Math.abs(signedDistanceToLine(l, axis));
    const vR = alongLine(r, axis), vL = alongLine(l, axis);
    const span = dR + dL || 1;
    const horizontal = (Math.abs(dR - dL) / span) * 100;   // normalised asymmetry index, in %
    const vertical = (Math.abs(vR - vL) / span) * 100;     // tilt of the pair, as % of its span
    rows.push({ label, right: dR, left: dL, horizontal, vertical, index: (horizontal + vertical) / 2 });
  }
  // Size pair: the two eyes
  const eyeIdx = (Math.abs(m.eyeWidthR - m.eyeWidthL) / (m.eyeWidthR + m.eyeWidthL || 1)) * 100;
  rows.push({ label: 'eye width', right: m.eyeWidthR, left: m.eyeWidthL, horizontal: eyeIdx, vertical: 0, index: eyeIdx, sizeOnly: true });

  const index = mean(rows.map((r) => r.index));
  const worst = rows.reduce((a, b) => (b.index > a.index ? b : a), rows[0]);
  return {
    index, score: symmetryScore(index), rows, worst,
    midline: { p: axis.p, d: axis.d },
    explain: `For each pair of matching points, the mirror measures how far each sits from the facial axis (a line fitted through ${MIDLINE.length} midline points) and how level the pair is. Asymmetry = |right − left| ÷ (right + left), in percent. Differences under 3% are invisible to the eye (Farkas & Cheung 1981).`,
  };
}

/* ------------------------------------------------------------------ verdict */

export const TIERS = [
  { min: 95, label: 'Fairest of them all', line: 'The mirror has rarely seen proportions this close to the golden ideal.' },
  { min: 90, label: 'A face for the golden age', line: 'Within a whisper of phi on nearly every measure.' },
  { min: 85, label: 'Classically harmonious', line: 'The proportions the old masters would have reached for.' },
  { min: 80, label: 'Charmingly proportioned', line: 'Close to the ideal where it counts, with a signature or two of your own.' },
  { min: 70, label: 'Distinctively yours', line: 'Your face keeps its own counsel on a few of the ratios, and is the more memorable for it.' },
  { min: 0, label: 'Beyond the formula', line: 'Phi was never going to capture you, and honestly, the sculptors would have asked you to sit anyway.' },
];

export function tierFor(score) {
  return TIERS.find((t) => score >= t.min) || TIERS[TIERS.length - 1];
}

const fmtPct = (f) => `${Math.abs(f * 100).toFixed(1)}%`;

export function describeDeviation(metric) {
  const d = metric.deviation;
  if (Math.abs(d) < 0.005) return 'spot on the ideal';
  const more = d > 0;
  return `${fmtPct(d)} ${more ? 'above' : 'below'} the ideal`;
}

/** Quality notes from the capture context. */
export function qualityNotes(ctx = {}) {
  const notes = [];
  const pose = ctx.pose;
  if (pose) {
    const parts = [];
    if (Math.abs(pose.yaw) > 7) parts.push(`turned ${Math.abs(pose.yaw).toFixed(0)}° to your ${pose.yaw > 0 ? 'left' : 'right'}`);
    if (Math.abs(pose.pitch) > 8) parts.push(`chin ${pose.pitch > 0 ? 'raised' : 'lowered'} ${Math.abs(pose.pitch).toFixed(0)}°`);
    if (Math.abs(pose.roll) > 5) parts.push(`tilted ${Math.abs(pose.roll).toFixed(0)}°`);
    if (parts.length) notes.push({ kind: 'warn', text: `Your head was ${parts.join(', ')}. A turned or tilted head foreshortens the face and skews the ratios; a straight-on reading will be fairer.` });
  }
  const e = ctx.expression;
  if (e) {
    if (e.smile > 0.35) notes.push({ kind: 'warn', text: `You were smiling (smile ${Math.round(e.smile * 100)}%). A smile widens the mouth and the nostrils, which lowers the mouth and nose ratios. Lovely, but not neutral.` });
    if (e.jawOpen > 0.2) notes.push({ kind: 'warn', text: 'Your lips were parted, which lengthens the lower face. Close them gently for a fairer reading.' });
    if (e.blink > 0.5) notes.push({ kind: 'warn', text: 'Your eyes were closing during the capture, so the eye points are less reliable.' });
    if (e.browUp > 0.5) notes.push({ kind: 'info', text: 'Your eyebrows were raised, which stretches the upper face a little.' });
  }
  if (ctx.source === 'photo') notes.push({ kind: 'info', text: 'Read from a photograph. Wide-angle selfies taken close to the face enlarge the nose and mouth; a photo taken from a metre or more away is kinder and truer.' });
  if (ctx.frames && ctx.frames > 1) notes.push({ kind: 'info', text: `Averaged over ${ctx.frames} video frames (median of each point) to steady the hand of the mirror.` });
  if (ctx.faceFrac && ctx.faceFrac < 0.25) notes.push({ kind: 'warn', text: 'Your face was small in the frame, so each pixel of error counts for more. Come closer next time.' });
  const h = ctx.hairline;
  if (h && h.found) {
    const mm = ctx.mmPerPx ? ` (about ${Math.round(h.pxAbove * ctx.mmPerPx)} mm)` : '';
    notes.push({ kind: 'info', text: `Hairline found ${Math.round(h.pxAbove)} pixels${mm} above the mesh’s top point, by following the forehead skin tone upwards; face length is measured from there.` });
  } else {
    notes.push({ kind: 'info', text: 'No hairline could be told apart from the forehead (hair close to the skin tone, a hat, or the forehead cut off), so face length is measured from the mesh’s top point, which sits about 13 mm under an average hairline. Face length therefore runs a little short.' });
  }
  return notes;
}

/**
 * The full verdict.
 * @param {Array<{x:number,y:number}>} p  478 landmarks in pixel coordinates
 * @param {object} ctx  { pose, expression, source, frames, faceFrac, top }
 */
export function analyze(p, ctx = {}) {
  const top = ctx.hairline && ctx.hairline.found ? ctx.hairline.point : (ctx.top || null);
  const m = measure(p, { top });
  ctx = { ...ctx, mmPerPx: m.mmPerPx };
  const phi = goldenMetrics(p, m);
  const canons = canonMetrics(p, m);
  const modern = modernMetrics(p, m);
  const sym = symmetry(p, m);

  const wsum = phi.reduce((s, x) => s + x.weight, 0);
  const phiScore = phi.reduce((s, x) => s + x.score * x.weight, 0) / wsum;
  const canonScore = mean(canons.map((x) => x.score));
  const modernScore = mean(modern.map((x) => x.score));
  const score = WEIGHTS.phi * phiScore + WEIGHTS.symmetry * sym.score;
  const tier = tierFor(score);

  const best = [...phi].sort((a, b) => b.score - a.score)[0];
  const worst = [...phi].sort((a, b) => a.score - b.score)[0];
  const meanDev = mean(phi.map((x) => Math.abs(x.deviation))) * 100;

  const verdict = `${tier.line} Across the seven golden ratios your proportions sit ${meanDev.toFixed(1)}% from phi on average. Your closest match is ${best.name.toLowerCase()} (${best.measured.toFixed(3)} against ${best.ideal.toFixed(3)}); the one the mirror teases you about is ${worst.name.toLowerCase()} (${worst.measured.toFixed(3)}). Your symmetry index is ${sym.index.toFixed(1)}%, ${sym.index < 3 ? 'below the 3% the eye can notice' : 'which the eye may just notice'}.`;

  return {
    score, scoreRounded: round(score, 1), tier, verdict,
    groups: {
      phi: { score: phiScore, metrics: phi, weight: WEIGHTS.phi },
      canons: { score: canonScore, metrics: canons },
      modern: { score: modernScore, metrics: modern },
    },
    symmetry: sym,
    allMetrics: [...phi, ...canons, ...modern],
    measurements: m,
    mmPerPx: m.mmPerPx,
    hairline: ctx.hairline || null,
    notes: qualityNotes(ctx),
    arithmetic: [
      `score = ${WEIGHTS.phi} × golden + ${WEIGHTS.symmetry} × symmetry`,
      `      = ${WEIGHTS.phi} × ${phiScore.toFixed(2)} + ${WEIGHTS.symmetry} × ${sym.score.toFixed(2)}`,
      `      = ${score.toFixed(2)}`,
      ``,
      `golden   = mean of the ${phi.length} ratio scores, each 100 × (1 − |measured − φ| ÷ φ)`,
      `symmetry = 100 − ${SYMMETRY_POINTS_PER_PERCENT} × asymmetry% (${sym.index.toFixed(2)}%)`,
    ].join('\n'),
  };
}

/* ------------------------------------------------------------------ synthetic faces (tests and references) */

/** Build a measurement object straight from named distances (for population references), bypassing landmarks. */
export function metricsFromDistances(d) {
  // d: { faceLength, faceWidth, mouthWidth, noseWidth, noseLength, outerEyeSpan, innerEyeSpan, eyeWidth, interpupillary,
  //      glabellaToSubnasale, subnasaleToMenton, eyesToStomion, alarToStomion, noseTipToMenton, stomionToMenton, subnasaleToStomion }
  const fake = (num, den, def) => makeMetric({ ...def, num, den }, null, []);
  const N = (label, key) => ({ label, value: d[key] });
  const defs = {
    faceLW: ['face length', 'faceWidth'], mouthNose: ['mouthWidth', 'noseWidth'], eyesMouth: ['outerEyeSpan', 'mouthWidth'],
    lipsChin: ['stomionToMenton', 'alarToStomion'], noseTipChin: ['noseTipToMenton', 'stomionToMenton'], eyesLips: ['eyesToStomion', 'stomionToMenton'],
    noseLW: ['noseLength', 'noseWidth'],
    thirds: ['glabellaToSubnasale', 'subnasaleToMenton'], fifths: ['outerEyeSpan', 'faceWidth'], noseEyes: ['noseWidth', 'innerEyeSpan'],
    mouthNoseCanon: ['mouthWidth', 'noseWidth'], faceNose: ['faceWidth', 'noseWidth'], lipsCanon: ['stomionToMenton', 'subnasaleToStomion'],
    pallettV: ['eyesToStomion', 'faceLength'], pallettH: ['interpupillary', 'faceWidth'],
  };
  defs.faceLW[0] = 'faceLength';
  const ideals = { faceLW: PHI, mouthNose: PHI, eyesMouth: PHI, lipsChin: PHI, noseTipChin: PHI, eyesLips: PHI, noseLW: PHI, thirds: 1, fifths: 0.6, noseEyes: 1, mouthNoseCanon: 1.5, faceNose: 4, lipsCanon: 2, pallettV: 0.36, pallettH: 0.46 };
  const groups = { faceLW: 'phi', mouthNose: 'phi', eyesMouth: 'phi', lipsChin: 'phi', noseTipChin: 'phi', eyesLips: 'phi', noseLW: 'phi', thirds: 'canon', fifths: 'canon', noseEyes: 'canon', mouthNoseCanon: 'canon', faceNose: 'canon', lipsCanon: 'canon', pallettV: 'modern', pallettH: 'modern' };
  const out = {};
  for (const [id, [nk, dk]] of Object.entries(defs)) {
    if (d[nk] == null || d[dk] == null) continue;
    out[id] = fake(N(nk, nk), N(dk, dk), { id, group: groups[id], name: id, ideal: ideals[id] });
  }
  return out;
}

/** Score a reference face described by named distances (symmetry assumed perfect unless given). */
export function scoreDistances(d, asymmetryPercent = 0) {
  const ms = metricsFromDistances(d);
  const phi = Object.values(ms).filter((x) => x.group === 'phi');
  const canons = Object.values(ms).filter((x) => x.group === 'canon');
  const modern = Object.values(ms).filter((x) => x.group === 'modern');
  const phiScore = mean(phi.map((x) => x.score));
  const symScore = symmetryScore(asymmetryPercent);
  return {
    score: WEIGHTS.phi * phiScore + WEIGHTS.symmetry * symScore,
    phiScore, canonScore: mean(canons.map((x) => x.score)), modernScore: mean(modern.map((x) => x.score)), symScore,
    metrics: ms,
  };
}
