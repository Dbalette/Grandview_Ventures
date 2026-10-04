/* Rendering the verdict: the dial, the still with its measurement lines, the itemised breakdown,
   the second opinions, the comparisons and the arithmetic. */
import { drawStill } from './overlay.js';
import { scoreDistances, describeDeviation, WEIGHTS, SYMMETRY_POINTS_PER_PERCENT, PHI } from './phi.js';
import { referenceDistances, FARKAS, REFERENCE_ASYMMETRY_PERCENT, BENCHMARKS } from './norms.js';

const el = (tag, attrs = {}, ...children) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'style') n.setAttribute('style', v);
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
};

const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
const f3 = (v) => v.toFixed(3);
const fmtLen = (px, mmPerPx) => (mmPerPx && isFinite(mmPerPx) ? `${px.toFixed(0)} px ≈ ${(px * mmPerPx).toFixed(0)} mm` : `${px.toFixed(0)} px`);

/* ----------------------------------------------------------------- hero */
function buildHero(result) {
  const r = 86, C = 2 * Math.PI * r;
  const svg = `
    <svg viewBox="0 0 200 200" role="img" aria-label="Score ${f1(result.score)} out of 100">
      <defs><linearGradient id="goldgrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e8cf8e"/><stop offset=".6" stop-color="#c9a14a"/><stop offset="1" stop-color="#9a7629"/></linearGradient></defs>
      <circle class="dial-track" cx="100" cy="100" r="${r}"/>
      <circle class="dial-arc" cx="100" cy="100" r="${r}" stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="${C.toFixed(2)}" data-target="${(C * (1 - result.score / 100)).toFixed(2)}"/>
    </svg>`;
  const dial = el('div', { class: 'dial', html: svg });
  dial.append(el('div', { class: 'dial-number' }, el('div', {}, el('b', {}, f1(result.score)), el('small', {}, 'of 100'))));
  const text = el('div', { class: 'verdict-text' },
    el('p', { class: 'tier' }, result.tier.label),
    el('p', { class: 'verdict-line' }, result.verdict),
  );
  const hero = el('div', { class: 'verdict-hero' }, dial, text);
  requestAnimationFrame(() => requestAnimationFrame(() => { const arc = dial.querySelector('.dial-arc'); arc.style.strokeDashoffset = arc.dataset.target; }));
  return hero;
}

function buildNotes(notes) {
  if (!notes || !notes.length) return null;
  return el('div', { class: 'notes' }, notes.map((n) => el('div', { class: `note ${n.kind === 'info' ? 'info' : ''}` }, n.text)));
}

/* ----------------------------------------------------------------- still */
function buildStill(media, result, onActiveChange) {
  const canvas = el('canvas', { 'aria-label': 'Your face with the measurement lines drawn on it' });
  const wrap = el('div', { class: 'still-wrap' }, canvas);
  const legend = el('div', { class: 'legend' }, result.groups.phi.metrics.map((m) => el('span', {}, el('i', { class: 'swatch', style: `--c:${m.color}` }), m.name)));
  const fig = el('figure', { class: 'still-figure' }, wrap, el('figcaption', { class: 'legend-wrap' }, legend, el('div', { class: 'fineprint', style: 'margin-top:6px' }, 'Tap a measurement below to light up its lines. The dashed gold line is the facial axis used for symmetry.')));
  let active = null;
  const redraw = () => drawStill(canvas, media.image, media.width, media.height, media.landmarks, result, { mirror: media.mirror, activeId: active });
  redraw();
  return {
    node: fig, canvas,
    setActive(id) { active = active === id ? null : id; redraw(); onActiveChange && onActiveChange(active); },
    getActive: () => active,
  };
}

/* ----------------------------------------------------------------- metric rows */
function metricDetail(m, mmPerPx) {
  const lines = [
    `${m.num.label} = ${fmtLen(m.num.value, mmPerPx)}`,
    `${m.den.label} = ${fmtLen(m.den.value, mmPerPx)}`,
    `ratio = ${m.num.value.toFixed(1)} ÷ ${m.den.value.toFixed(1)} = ${f3(m.measured)}`,
    `ideal = ${f3(m.ideal)}${m.idealLabel ? ` (${m.idealLabel})` : ''}`,
    `deviation = |${f3(m.measured)} − ${f3(m.ideal)}| ÷ ${f3(m.ideal)} = ${(Math.abs(m.deviation) * 100).toFixed(1)}%`,
    `score = 100 − ${(Math.abs(m.deviation) * 100).toFixed(1)} = ${f1(m.score)}`,
  ];
  return el('div', { class: 'metric-detail', hidden: true },
    el('p', {}, m.explain),
    el('div', { class: 'math' }, lines.join('\n')),
    el('p', { class: 'fineprint', style: 'text-align:left;margin:4px 0 0' }, `Source: ${m.source}.`),
  );
}

function buildMetricList(metrics, mmPerPx, still) {
  const list = el('ul', { class: 'metrics' });
  for (const m of metrics) {
    const detail = metricDetail(m, mmPerPx);
    const head = el('button', { class: 'metric-head', type: 'button', 'aria-expanded': 'false' },
      el('span', { class: 'swatch', style: `--c:${m.color}` }),
      el('span', { class: 'metric-name' }, m.name, el('small', {}, m.formula)),
      el('span', { class: 'metric-score' }, f1(m.score)),
      el('span', { class: 'chev', 'aria-hidden': 'true' }),
    );
    const grid = el('div', { class: 'metric-grid' },
      el('div', {}, el('small', {}, 'You'), el('b', {}, f3(m.measured))),
      el('div', {}, el('small', {}, 'Ideal'), el('b', {}, m.idealLabel && m.idealLabel.length <= 3 ? `${f3(m.ideal)} ${m.idealLabel}` : f3(m.ideal))),
      el('div', {}, el('small', {}, 'Off by'), el('b', {}, `${(Math.abs(m.deviation) * 100).toFixed(1)}%`)),
      el('div', {}, el('small', {}, 'Reads'), el('b', {}, m.deviation > 0 ? 'high' : 'low')),
    );
    const bar = el('div', { class: 'metric-bar' }, el('i', { style: 'width:0%' }));
    const li = el('li', { class: 'metric', 'data-id': m.id }, head, grid, bar, detail);
    head.addEventListener('click', () => {
      const open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', String(!open));
      detail.hidden = open;
      still.setActive(m.id);
    });
    list.append(li);
    requestAnimationFrame(() => { bar.firstChild.style.width = `${m.score}%`; });
  }
  // keep the "active" highlight in sync with the still
  const sync = (activeId) => { for (const li of list.children) li.classList.toggle('is-active', li.dataset.id === activeId); };
  return { node: list, sync };
}

function panel(title, score, intro, ...children) {
  const h = el('h3', {}, title);
  if (score !== null && score !== undefined) h.append(el('span', { class: 'panel-score' }, 'score ', el('b', {}, f1(score))));
  return el('section', { class: 'panel' }, h, intro ? el('p', { class: 'panel-intro' }, intro) : null, ...children);
}

/* ----------------------------------------------------------------- symmetry */
function buildSymmetry(sym) {
  const rows = el('div', { class: 'pairs' },
    el('span', { class: 'h' }, 'Pair'), el('span', { class: 'h' }, 'Right / left'), el('span', { class: 'h' }, 'Asymmetry'),
    ...sym.rows.flatMap((r) => [
      el('span', {}, r.label),
      el('span', {}, `${r.right.toFixed(0)} / ${r.left.toFixed(0)} px`),
      el('b', {}, `${r.index.toFixed(1)}%`),
    ]),
  );
  return panel('Symmetry', sym.score, sym.explain,
    rows,
    el('div', { class: 'math formula' }, `asymmetry index = mean over ${sym.rows.length} pairs = ${sym.index.toFixed(2)}%\nscore = 100 − ${SYMMETRY_POINTS_PER_PERCENT} × ${sym.index.toFixed(2)} = ${f1(sym.score)}`),
    el('p', { class: 'fineprint', style: 'text-align:left' }, `Your least symmetrical pair: ${sym.worst.label} (${sym.worst.index.toFixed(1)}%). Camera lenses and a head turned by even a few degrees add asymmetry that is not yours.`),
  );
}

/* ----------------------------------------------------------------- comparisons */
function buildCompare(result) {
  const refs = ['female', 'male'].map((k) => {
    const r = scoreDistances(referenceDistances(k), REFERENCE_ASYMMETRY_PERCENT);
    return { name: FARKAS[k].label, sub: `Farkas calipers, North American White ${k === 'female' ? 'women' : 'men'} 18–25, n = ${FARKAS[k].n}, same rules`, score: r.score, kind: 'ref' };
  });
  const rows = [
    { name: 'You', sub: 'this reading', score: result.score, kind: 'you' },
    ...refs,
    ...BENCHMARKS.map((b) => ({ name: b.name, sub: `De Silva face mapping, ${b.year}`, score: b.score, kind: 'bench' })),
  ].sort((a, b) => b.score - a.score);
  const list = el('ul', { class: 'bench' }, rows.map((r) => el('li', { class: r.kind === 'you' ? 'you' : '' },
    el('span', { class: 'who' }, r.name, el('small', {}, r.sub)),
    el('span', { class: 'val' }, f1(r.score)),
    el('span', { class: 'track' }, el('i', { style: `width:${Math.max(0, Math.min(100, (r.score - 70) / 30 * 100))}%` })),
  )));
  return panel('How you compare', null,
    'Two kinds of company. The two average faces are Farkas’s caliper norms pushed through exactly the mirror’s formulas, so they are a fair yardstick (calipers see the nose a little narrower and the hairline a little higher than a camera does, which is worth a point or two). The celebrity figures are Dr Julian De Silva’s press-released scores from an unpublished 12-marker method; they are on a similar 100-point phi scale but not the same instrument. The bars run from 70 to 100.',
    list,
  );
}

/* ----------------------------------------------------------------- arithmetic */
function buildArithmetic(result) {
  return panel('The arithmetic', null, null,
    el('div', { class: 'formula' }, result.arithmetic),
    el('p', {}, `φ = (1 + √5) ÷ 2 = ${PHI.toFixed(9)}. Every golden ratio is scored the same way: the measured ratio is compared with φ and each percent of deviation costs one point. The seven ratio scores are averaged, that average carries ${WEIGHTS.phi * 100}% of the headline and the symmetry score the other ${WEIGHTS.symmetry * 100}%. The classical canons and the modern ratios are shown as second opinions and do not move the headline.`),
    el('p', { class: 'caveat' }, 'A word from the mirror’s conscience: the golden ratio is a 2,400-year-old hypothesis about beauty, not a law. Controlled studies (Holland 2008; Kiekens 2008; Pallett 2010; systematic reviews in 2022 and 2024) find it a weak predictor of who people actually find attractive; averageness, symmetry, skin and expression do more work. Take the number as a parlour game with honest arithmetic, and the face in the glass as the thing itself.'),
  );
}

/* ----------------------------------------------------------------- main */
export function renderVerdict(root, result, media) {
  root.innerHTML = '';
  const mm = result.mmPerPx;
  let lists = [];
  const still = buildStill(media, result, (activeId) => lists.forEach((l) => l.sync(activeId)));
  const phiList = buildMetricList(result.groups.phi.metrics, mm, still);
  const canonList = buildMetricList(result.groups.canons.metrics, mm, still);
  const modernList = buildMetricList(result.groups.modern.metrics, mm, still);
  lists = [phiList, canonList, modernList];

  root.append(
    buildHero(result),
    buildNotes(result.notes),
    still.node,
    panel('The seven golden ratios', result.groups.phi.score, `Each is a ratio of two distances on your face, compared with φ = ${PHI.toFixed(3)}. Tap a row for the full working.`, phiList.node),
    buildSymmetry(result.symmetry),
    panel('Second opinion: the classical canons', result.groups.canons.score, 'The sculptors’ rules of thumb, from the Greeks to Leonardo to the 20th-century anthropometrist Leslie Farkas, who measured how often they are actually true (rarely).', canonList.node),
    panel('Second opinion: modern science', result.groups.modern.score, 'What a 2010 experiment on real preferences found, instead of what the ancients assumed. The ideal turned out to be the average.', modernList.node),
    buildCompare(result),
    buildArithmetic(result),
  );
  if (mm && isFinite(mm)) {
    root.append(el('p', { class: 'fineprint' }, `Millimetre figures are estimated from your iris, whose diameter is almost the same in every adult (${(11.7).toFixed(1)} mm), giving ${(mm * 100).toFixed(2)} mm per 100 px here.`));
  }
  return { still };
}

/** A shareable card: the still with lines, the score, the tier and the seven ratios. */
export function composeCard(result, media) {
  const W = 1080, H = 1620;
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#faf3e7'; ctx.fillRect(0, 0, W, H);
  // frame
  ctx.strokeStyle = '#c9a14a'; ctx.lineWidth = 6; ctx.strokeRect(30, 30, W - 60, H - 60);
  ctx.lineWidth = 1.5; ctx.strokeRect(44, 44, W - 88, H - 88);
  ctx.fillStyle = '#6e1e2b'; ctx.textAlign = 'center';
  ctx.font = 'italic 600 64px "Playfair Display", Georgia, serif'; ctx.fillText('Mirror Mirror on The Wall', W / 2, 130);
  ctx.font = '400 26px "Josefin Sans", "Segoe UI", sans-serif'; ctx.fillStyle = '#7d6a6e'; ctx.fillText('A magic mirror that answers in mathematics', W / 2, 172);
  // still
  const tmp = document.createElement('canvas');
  drawStill(tmp, media.image, media.width, media.height, media.landmarks, result, { mirror: media.mirror, activeId: null, maxEdge: 1000 });
  const box = { x: 90, y: 210, w: W - 180, h: 760 };
  const s = Math.min(box.w / tmp.width, box.h / tmp.height);
  const dw = tmp.width * s, dh = tmp.height * s, dx = box.x + (box.w - dw) / 2, dy = box.y + (box.h - dh) / 2;
  ctx.save(); ctx.shadowColor = 'rgba(78,32,40,.25)'; ctx.shadowBlur = 30; ctx.shadowOffsetY = 12; ctx.fillStyle = '#000'; ctx.fillRect(dx, dy, dw, dh); ctx.restore();
  ctx.drawImage(tmp, dx, dy, dw, dh);
  ctx.strokeStyle = '#c9a14a'; ctx.lineWidth = 4; ctx.strokeRect(dx, dy, dw, dh);
  // score
  ctx.fillStyle = '#6e1e2b'; ctx.font = '600 150px "Playfair Display", Georgia, serif'; ctx.fillText(f1(result.score), W / 2, 1140);
  ctx.font = '400 26px "Josefin Sans", sans-serif'; ctx.fillStyle = '#7d6a6e'; ctx.fillText('OUT OF 100 · GOLDEN RATIO SCORE', W / 2, 1180);
  ctx.font = 'italic 600 46px "Playfair Display", Georgia, serif'; ctx.fillStyle = '#6e1e2b'; ctx.fillText(result.tier.label, W / 2, 1245);
  // ratios
  ctx.textAlign = 'left'; ctx.font = '400 26px "Josefin Sans", sans-serif';
  const ms = result.groups.phi.metrics; const col = [100, 560];
  ms.forEach((m, i) => {
    const x = col[i % 2], y = 1310 + Math.floor(i / 2) * 44;
    ctx.fillStyle = m.color; ctx.fillRect(x, y - 20, 16, 16);
    ctx.fillStyle = '#2b1d20'; ctx.fillText(`${m.name.replace(' ÷ ', ' / ')}`, x + 28, y - 6);
    ctx.fillStyle = '#6e1e2b'; ctx.font = '600 26px "Josefin Sans", sans-serif'; ctx.fillText(f1(m.score), x + 400, y - 6); ctx.font = '400 26px "Josefin Sans", sans-serif';
  });
  ctx.textAlign = 'center'; ctx.fillStyle = '#7d6a6e'; ctx.font = 'italic 400 24px "Playfair Display", Georgia, serif';
  ctx.fillText(`symmetry ${f1(result.symmetry.score)} · φ = 1.618 · a parlour game with honest arithmetic`, W / 2, H - 72);
  return c;
}
