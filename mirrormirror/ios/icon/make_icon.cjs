// Mirror Mirror on The Wall: the restrained version. A gold-bezelled oval mirror whose glass holds an exact golden spiral
// drawn over the golden-rectangle construction it comes from.
// Usage: node make_icon.cjs <outDir> [wine|navy] [--web <iconsDir>]
// Writes <outDir>/icon.svg and <outDir>/icon-1024.png (opaque, square: iOS rounds the corners itself).
// With --web it also writes the web app's icon set into <iconsDir>: a light rounded icon.svg for the favicon and manifest,
// icon-192.png and icon-512.png with rounded corners, an opaque apple-touch-icon.png, and a full-bleed icon-maskable-512.png.
// ROT (90 or 270) and FLIP (0 or 1) choose which way the spiral turns; PRINT=1 lists where the eye lands for each choice.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || '.';
const THEME_NAME = process.argv[3] || 'wine';
const f = (n) => n.toFixed(1);

const THEME = {
  wine: {
    bg: ['#702039', '#4c1126', '#34091a'],
    halo: ['#ffb98a', 0.20],
    glass: ['#5a2e4d', '#2a1529', '#130a14'],
    glassEdge: '#0d0509',
    eyeGlow: ['#d9a3d4', 0.30],
  },
  navy: {
    bg: ['#1c3a6b', '#102448', '#08142a'],
    halo: ['#9cc3ff', 0.18],
    glass: ['#31507f', '#162845', '#0a1425'],
    glassEdge: '#050a14',
    eyeGlow: ['#8fb4f0', 0.30],
  },
}[THEME_NAME];

const PHI = (1 + Math.sqrt(5)) / 2;
const W = 1024, CX = 512, CY = 520;
const A = 292, B = 404, TH = 40;          // outer frame radii and bezel thickness
const GA = A - TH, GB = B - TH;            // glass radii
const ROT = Number(process.env.ROT ?? 270), FLIP = (process.env.FLIP ?? '0') === '1';
const NQ = Number(process.env.NQ ?? 8.5);  // quarter turns drawn from the outer corner towards the eye

// ---------- golden rectangle, landscape [0,PHI] x [0,1], y down ----------
const POLE = [PHI ** 3 / (PHI ** 2 + 1), PHI ** 3 / (PHI ** 2 + 1) / PHI];   // the eye of the spiral, (1.1708, 0.7236)
function squares(n) {
  // cut a square from the left, top, right, bottom in turn, clockwise inwards
  let [x0, y0, x1, y1] = [0, 0, PHI, 1];
  const out = [];
  for (let i = 0; i < n; i++) {
    const w = x1 - x0, h = y1 - y0, side = Math.min(w, h), k = i % 4;
    if (k === 0) { out.push([x0, y0, side]); x0 += side; }
    else if (k === 1) { out.push([x0, y0, side]); y0 += side; }
    else if (k === 2) { out.push([x1 - side, y0, side]); x1 -= side; }
    else { out.push([x0, y1 - side, side]); y1 -= side; }
  }
  return out;
}
// Exact spiral through the square corners: the radius shrinks by phi every quarter turn, clockwise on screen.
function spiral(samples) {
  const rx = 0 - POLE[0], ry = 1 - POLE[1], r0 = Math.hypot(rx, ry), th0 = Math.atan2(ry, rx);
  const pts = [];
  for (let i = 0; i <= samples; i++) {
    const u = i / samples, q = (1 - u) * NQ, r = r0 * Math.pow(PHI, -q), th = th0 + (q * Math.PI) / 2;
    pts.push([POLE[0] + r * Math.cos(th), POLE[1] + r * Math.sin(th), u, r / r0]);
  }
  return pts;
}

// ---------- placement in the glass ----------
const MARGIN = 34;
const S = 2 / Math.sqrt(1 / (GA - MARGIN) ** 2 + PHI ** 2 / (GB - MARGIN) ** 2);   // px per unit so the rectangle fits the glass
function toCanvas(p) {
  let x = p[0] - PHI / 2, y = p[1] - 0.5;
  if (FLIP) x = -x;
  const r = (ROT * Math.PI) / 180, c = Math.round(Math.cos(r)), s = Math.round(Math.sin(r));
  const rx = x * c - y * s, ry = x * s + y * c;
  return [CX + rx * S, CY + ry * S];
}
if (process.env.PRINT === '1') {
  for (const flip of [false, true]) for (const rot of [90, 270]) {
    let x = POLE[0] - PHI / 2, y = POLE[1] - 0.5;
    if (flip) x = -x;
    const r = (rot * Math.PI) / 180, c = Math.round(Math.cos(r)), s = Math.round(Math.sin(r));
    console.log(`ROT ${rot} FLIP ${flip ? 1 : 0}: eye at (${f(CX + (x * c - y * s) * S)}, ${f(CY + (x * s + y * c) * S)}), scale ${f(S)} px per unit`);
  }
  process.exit(0);
}

// ---------- shapes ----------
function widthAt(u, rho) {
  const taper = u < 0.93 ? 1 : 1 - 0.7 * Math.pow((u - 0.93) / 0.07, 2);
  return Math.max(3.2, 21 * Math.pow(rho, 0.5) * taper);
}
function ribbon(pts, scale = 1, grow = 0, shift = 0) {
  const n = pts.length, left = [], right = [];
  for (let i = 0; i < n; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)];
    let tx = b[0] - a[0], ty = b[1] - a[1];
    const m = Math.hypot(tx, ty) || 1; tx /= m; ty /= m;
    const nx = -ty, ny = tx, w = widthAt(pts[i][2], pts[i][3]) * scale + grow;
    const cx = pts[i][0] + nx * shift * w, cy = pts[i][1] + ny * shift * w;
    left.push([cx + (nx * w) / 2, cy + (ny * w) / 2]);
    right.push([cx - (nx * w) / 2, cy - (ny * w) / 2]);
  }
  return 'M' + left.concat(right.reverse()).map((p) => f(p[0]) + ' ' + f(p[1])).join(' L') + ' Z';
}
function equalArc(a, b, n, start = -Math.PI / 2) {
  const M = 8000, ts = [], ls = [0];
  for (let i = 0; i <= M; i++) ts.push(start + (2 * Math.PI * i) / M);
  for (let i = 1; i <= M; i++) ls.push(ls[i - 1] + Math.hypot(a * (Math.cos(ts[i]) - Math.cos(ts[i - 1])), b * (Math.sin(ts[i]) - Math.sin(ts[i - 1]))));
  const L = ls[M], out = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const t = (k * L) / n;
    while (ls[j + 1] < t) j++;
    out.push(ts[j] + ((t - ls[j]) / (ls[j + 1] - ls[j])) * (ts[j + 1] - ts[j]));
  }
  return out;
}
function star(cx, cy, r, k = 0.13) {
  const q = r * k;
  return `M${f(cx)} ${f(cy - r)} Q${f(cx + q)} ${f(cy - q)} ${f(cx + r)} ${f(cy)} Q${f(cx + q)} ${f(cy + q)} ${f(cx)} ${f(cy + r)} ` +
    `Q${f(cx - q)} ${f(cy + q)} ${f(cx - r)} ${f(cy)} Q${f(cx - q)} ${f(cy - q)} ${f(cx)} ${f(cy - r)} Z`;
}

const spiralPts = (n) => spiral(n).map((p) => [...toCanvas(p), p[2], p[3]]);
const eye = toCanvas(POLE);
const rectPath = (x, y, s, h = s) => 'M' + [[x, y], [x + s, y], [x + s, y + h], [x, y + h]].map((p) => toCanvas(p).map(f).join(' ')).join(' L') + ' Z';
const guideSquares = squares(9).map(([x, y, s]) => rectPath(x, y, s)).join(' ');
const guideOuter = rectPath(0, 0, PHI, 1);

const beads = equalArc(A - TH / 2, B - TH / 2, 120).map((t) => {
  const x = CX + (A - TH / 2) * Math.cos(t), y = CY + (B - TH / 2) * Math.sin(t);
  return `<circle cx="${f(x)}" cy="${f(y)}" r="6.4" fill="url(#bead)"/>`;
}).join('');

// flare on the bezel, upper left
const flare = [CX - A * 0.672, CY - B * 0.70];

function buildSvg({ lite = false, round = false } = {}) {
  const pts = spiralPts(lite ? 160 : 900);
  const guides = lite ? '' : `<path d="${guideSquares}" fill="none" stroke="#f1d58a" stroke-opacity=".26" stroke-width="2.4" stroke-linejoin="round"/>
  <path d="${guideOuter}" fill="none" stroke="#f1d58a" stroke-opacity=".42" stroke-width="2.4" stroke-linejoin="round"/>`;
  const beadRing = lite ? '' : `<g filter="url(#beadShadow)">${beads}</g>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${W}" width="${W}" height="${W}">
<defs>
  <radialGradient id="bg" cx="${CX}" cy="${CY - 70}" r="640" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="${THEMES_BG(0)}"/><stop offset=".48" stop-color="${THEMES_BG(1)}"/><stop offset=".84" stop-color="${THEMES_BG(2)}"/><stop offset="1" stop-color="${THEMES_BG(2)}"/>
  </radialGradient>
  <radialGradient id="halo" cx="${CX}" cy="${CY}" r="430" gradientUnits="userSpaceOnUse">
    <stop offset=".35" stop-color="${THEME.halo[0]}" stop-opacity="${THEME.halo[1]}"/><stop offset="1" stop-color="${THEME.halo[0]}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="gold" x1="${CX - A}" y1="${CY - B}" x2="${CX + A}" y2="${CY + B}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff2c0"/><stop offset=".2" stop-color="#efcf7a"/><stop offset=".46" stop-color="#cfa341"/><stop offset=".72" stop-color="#8d6420"/><stop offset=".9" stop-color="#d9b560"/><stop offset="1" stop-color="#f3dc98"/>
  </linearGradient>
  <linearGradient id="goldRev" x1="${CX + A}" y1="${CY + B}" x2="${CX - A}" y2="${CY - B}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff0b8"/><stop offset=".45" stop-color="#cfa44a"/><stop offset=".85" stop-color="#7a5316"/><stop offset="1" stop-color="#e5c87f"/>
  </linearGradient>
  <linearGradient id="glassFill" x1="${CX - GA}" y1="${CY - GB}" x2="${CX + GA * 0.9}" y2="${CY + GB}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="${THEME.glass[0]}"/><stop offset=".5" stop-color="${THEME.glass[1]}"/><stop offset="1" stop-color="${THEME.glass[2]}"/>
  </linearGradient>
  <radialGradient id="vignette" cx="${CX}" cy="${CY}" r="${GB}" gradientUnits="userSpaceOnUse" gradientTransform="translate(${CX} ${CY}) scale(${GA / GB} 1) translate(${-CX} ${-CY})">
    <stop offset=".6" stop-color="${THEME.glassEdge}" stop-opacity="0"/><stop offset="1" stop-color="${THEME.glassEdge}" stop-opacity=".62"/>
  </radialGradient>
  <linearGradient id="spiralGold" x1="${CX - GA}" y1="${CY - GB}" x2="${CX + GA}" y2="${CY + GB}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff6cf"/><stop offset=".5" stop-color="#f0cc70"/><stop offset="1" stop-color="#c9983a"/>
  </linearGradient>
  <radialGradient id="eyeGlow" cx="${f(eye[0])}" cy="${f(eye[1])}" r="260" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${THEME.eyeGlow[0]}" stop-opacity="${THEME.eyeGlow[1]}"/><stop offset="1" stop-color="${THEME.eyeGlow[0]}" stop-opacity="0"/></radialGradient>
  <radialGradient id="bead" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff8dc"/><stop offset=".5" stop-color="#e3bd62"/><stop offset="1" stop-color="#8b6119"/></radialGradient>
  <linearGradient id="sheen" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".30"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <radialGradient id="glow"><stop offset="0" stop-color="#fffbe8" stop-opacity=".95"/><stop offset=".35" stop-color="#ffe9a8" stop-opacity=".42"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/></radialGradient>
  ${round ? `<clipPath id="tile"><rect width="${W}" height="${W}" rx="229" ry="229"/></clipPath>` : ''}
  <clipPath id="glassClip"><ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}"/></clipPath>
  <filter id="blur24" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="22"/></filter>
  <filter id="blur10" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>
  <filter id="blur2" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2"/></filter>
  <filter id="beadShadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx=".8" dy="1.6" stdDeviation="1.2" flood-color="#2e1a04" flood-opacity=".6"/></filter>
</defs>
${round ? '<g clip-path="url(#tile)">' : '<g>'}
<rect width="${W}" height="${W}" fill="${THEMES_BG(2)}"/>
<rect width="${W}" height="${W}" fill="url(#bg)"/>
<ellipse cx="${CX}" cy="${CY}" rx="430" ry="470" fill="url(#halo)"/>

<!-- mirror -->
<ellipse cx="${CX + 8}" cy="${CY + 30}" rx="${A}" ry="${B}" fill="#12040a" opacity=".6" filter="url(#blur24)"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A}" ry="${B}" fill="url(#gold)" stroke="#5a3b0a" stroke-width="3"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A - 7}" ry="${B - 7}" fill="none" stroke="#fff6cf" stroke-width="2.5" opacity=".7"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A - TH + 8}" ry="${B - TH + 8}" fill="none" stroke="#5a3b0a" stroke-width="2.5" opacity=".55"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A - TH + 11}" ry="${B - TH + 11}" fill="none" stroke="#fff0b8" stroke-width="1.5" opacity=".5"/>
${beadRing}
<ellipse cx="${CX}" cy="${CY}" rx="${GA + 5}" ry="${GB + 5}" fill="url(#goldRev)" stroke="#432b07" stroke-width="2"/>

<!-- glass -->
<ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="url(#glassFill)"/>
<g clip-path="url(#glassClip)">
  <ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="url(#vignette)"/>
  <rect x="${CX - GA}" y="${CY - GB}" width="${2 * GA}" height="${2 * GB}" fill="url(#eyeGlow)"/>
  ${guides}
  <path d="${ribbon(pts, 1, 14)}" fill="#f2c968" opacity=".42" filter="url(#blur10)"/>
  <path d="${ribbon(pts, 1, 0)}" fill="url(#spiralGold)"/>
  <path d="${ribbon(pts, 0.3, 0, -0.2)}" fill="#fffdf0" opacity=".8"/>
  <circle cx="${f(eye[0])}" cy="${f(eye[1])}" r="26" fill="url(#glow)"/>
  <circle cx="${f(eye[0])}" cy="${f(eye[1])}" r="7.5" fill="#fffaf0"/>
  <polygon points="${CX - 300},${CY - 40} ${CX - 120},${CY - 400} ${CX - 55},${CY - 400} ${CX - 270},${CY + 60}" fill="url(#sheen)" opacity=".5"/>
  <polygon points="${CX - 190},${CY + 190} ${CX + 20},${CY - 150} ${CX + 44},${CY - 150} ${CX - 166},${CY + 200}" fill="url(#sheen)" opacity=".22"/>
</g>
<ellipse cx="${CX}" cy="${CY}" rx="${GA - 1}" ry="${GB - 1}" fill="none" stroke="#fff3c4" stroke-opacity=".5" stroke-width="2"/>
<path d="M${f(CX + (GA - 14) * Math.cos(3.55))} ${f(CY + (GB - 14) * Math.sin(3.55))} A${GA - 14} ${GB - 14} 0 0 1 ${f(CX + (GA - 14) * Math.cos(4.35))} ${f(CY + (GB - 14) * Math.sin(4.35))}" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" opacity=".38" filter="url(#blur2)"/>

<!-- one glint on the bezel -->
<g><circle cx="${f(flare[0])}" cy="${f(flare[1])}" r="40" fill="url(#glow)"/>
<path d="${star(flare[0], flare[1], 30)}" fill="#fffaf0"/><path d="${star(flare[0], flare[1], 14, 0.2)}" transform="rotate(45 ${f(flare[0])} ${f(flare[1])})" fill="#fffaf0"/></g>
</g>
</svg>`;
}

function THEMES_BG(i) { return THEME.bg[i]; }

async function renderPng(page, svg, size, file, transparent) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(`<!doctype html><html><head><style>html,body{margin:0;background:${transparent ? 'transparent' : THEME.bg[2]}}svg{display:block;width:${size}px;height:${size}px}</style></head><body>${svg}</body></html>`);
  await page.waitForTimeout(200);
  await page.screenshot({ path: file, omitBackground: transparent, clip: { x: 0, y: 0, width: size, height: size } });
  console.log('wrote', file);
}

const webAt = process.argv.indexOf('--web');
const WEB = webAt >= 0 ? process.argv[webAt + 1] : null;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const full = buildSvg();
  fs.writeFileSync(path.join(OUT, 'icon.svg'), full);
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 1 });
  await renderPng(p, full, W, path.join(OUT, 'icon-1024.png'), false);
  if (WEB) {
    fs.mkdirSync(WEB, { recursive: true });
    fs.writeFileSync(path.join(WEB, 'icon.svg'), buildSvg({ lite: true, round: true }));
    console.log('wrote', path.join(WEB, 'icon.svg'));
    const rounded = buildSvg({ round: true });
    await renderPng(p, rounded, 512, path.join(WEB, 'icon-512.png'), true);
    await renderPng(p, rounded, 192, path.join(WEB, 'icon-192.png'), true);
    await renderPng(p, full, 180, path.join(WEB, 'apple-touch-icon.png'), false);
    await renderPng(p, full, 512, path.join(WEB, 'icon-maskable-512.png'), false);
  }
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
