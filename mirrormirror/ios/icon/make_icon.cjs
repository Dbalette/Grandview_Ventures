// Mirror Mirror on The Wall: 1950s vanity-mirror icon, a pearl-framed gold mirror with a satin bow and an exact golden spiral.
// Usage: node make_icon.cjs <outDir> [blush|magic]
// Writes <outDir>/icon.svg and <outDir>/icon-1024.png (opaque, square: iOS rounds the corners itself).
// The spiral is r = phi^(quarter turns), drawn as a tapered ribbon; ROTDEG and DIR (-1 or 1) choose its orientation,
// WMAX its thickness, NQ how many quarter turns it makes from the eye to the outer end. PRINT_FIT=1 lists the placements.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || '.';
const THEME = process.argv[3] || 'blush';
const PRINT_FIT = process.env.PRINT_FIT === '1';

const W = 1024, CX = 512, CY = 548;
const A = 318, B = 402;      // outer frame radii
const GA = 246, GB = 330;    // glass radii
const PA = 282, PB = 366;    // pearl centre-line radii

const T = {
  blush: {
    glass: ['#fff4f5', '#f8d2da', '#e8a6b8'],
    spiralFill: ['#fff0b8', '#e6bd55', '#b5832a'],
    spiralEdge: '#8a1c3c',
    edgeGrow: 9,
    eyeGlow: ['#ffffff', 0.6],
    wmax: 34,
  },
  magic: {
    glass: ['#5b3a52', '#2d1a2c', '#150b17'],
    spiralFill: ['#fff6cf', '#f1cf72', '#c9972f'],
    spiralEdge: '#3b2606',
    edgeGrow: 5,
    eyeGlow: ['#c58ad0', 0.42],
    wmax: 30,
  },
}[THEME];

// ---------- geometry helpers ----------
const f = (n) => n.toFixed(1);

function equalArcAngles(a, b, n, start = -Math.PI / 2) {
  const M = 8000, ts = [], ls = [0];
  for (let i = 0; i <= M; i++) ts.push(start + (2 * Math.PI * i) / M);
  for (let i = 1; i <= M; i++) {
    const dx = a * (Math.cos(ts[i]) - Math.cos(ts[i - 1]));
    const dy = b * (Math.sin(ts[i]) - Math.sin(ts[i - 1]));
    ls.push(ls[i - 1] + Math.hypot(dx, dy));
  }
  const L = ls[M], out = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const target = (k * L) / n;
    while (ls[j + 1] < target) j++;
    const u = (target - ls[j]) / (ls[j + 1] - ls[j]);
    out.push(ts[j] + u * (ts[j + 1] - ts[j]));
  }
  return out;
}

// Exact golden spiral: the radius grows by phi every quarter turn. Unit coordinates, outer end at radius 1.
const PHI = (1 + Math.sqrt(5)) / 2;
const NQ = Number(process.env.NQ ?? 6.75);        // quarter turns from the eye to the outer end
const WMAX = Number(process.env.WMAX ?? T.wmax);      // ribbon width at the outer end, px
function logSpiralUnit(rot, dir, samples) {
  const pts = [];
  for (let i = 0; i <= samples; i++) {
    const u = i / samples, q = u * NQ, rho = Math.pow(PHI, q - NQ), th = rot + dir * q * Math.PI / 2;
    pts.push([rho * Math.cos(th), rho * Math.sin(th), u, rho]);
  }
  return pts;
}
function widthAt(u, rho) {
  const taper = u < 0.9 ? 1 : 1 - 0.78 * Math.pow((u - 0.9) / 0.1, 2);
  return Math.max(3.5, WMAX * Math.pow(rho, 0.55) * taper);
}
function fit(rot, dir) {
  const pts = logSpiralUnit(rot, dir, 140);
  let best = null;
  for (let s = 380; s >= 150 && !best; s -= 4) {
    for (let ox = -100; ox <= 100; ox += 6) {
      for (let oy = -100; oy <= 100; oy += 6) {
        const ok = pts.every(([x, y, u, rho]) => {
          const m = widthAt(u, rho) / 2 + 16;
          return ((x * s + ox) / (GA - m)) ** 2 + ((y * s + oy) / (GB - m)) ** 2 <= 1;
        });
        if (ok) { best = { s, ox, oy }; break; }
      }
      if (best) break;
    }
  }
  return best;
}

// ---------- chosen placement ----------
const ROTDEG = Number(process.env.ROTDEG ?? 340), DIR = Number(process.env.DIR ?? -1);
if (PRINT_FIT) {
  for (const dir of [-1, 1]) for (let rd = 0; rd < 360; rd += 20) {
    const b = fit((rd * Math.PI) / 180, dir);
    if (!b) { console.log(rd, dir, 'no fit'); continue; }
    const pts = logSpiralUnit((rd * Math.PI) / 180, dir, 10);
    const e = pts[0], o = pts[pts.length - 1];
    console.log(`rot ${rd} dir ${dir}: outer radius ${b.s}, eye (${f(CX + e[0] * b.s + b.ox)}, ${f(CY + e[1] * b.s + b.oy)}), outer end (${f(CX + o[0] * b.s + b.ox)}, ${f(CY + o[1] * b.s + b.oy)})`);
  }
  process.exit(0);
}
const fitted = fit((ROTDEG * Math.PI) / 180, DIR);
if (!fitted) throw new Error('spiral does not fit');
const UNIT = logSpiralUnit((ROTDEG * Math.PI) / 180, DIR, 900);
const placed = UNIT.map(([x, y, u, rho]) => [CX + x * fitted.s + fitted.ox, CY + y * fitted.s + fitted.oy, u, rho]);

// Tapered ribbon along the spiral (a polygon with smooth edges). pts are [x, y, u, rho]; widths in px.
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
  const poly = left.concat(right.reverse());
  return 'M' + poly.map((p) => f(p[0]) + ' ' + f(p[1])).join(' L') + ' Z';
}

const eye = placed[0], endPt = placed[placed.length - 1];

function star(cx, cy, r, k = 0.13) {
  const q = r * k;
  return `M${f(cx)} ${f(cy - r)} Q${f(cx + q)} ${f(cy - q)} ${f(cx + r)} ${f(cy)} Q${f(cx + q)} ${f(cy + q)} ${f(cx)} ${f(cy + r)} ` +
    `Q${f(cx - q)} ${f(cy + q)} ${f(cx - r)} ${f(cy)} Q${f(cx - q)} ${f(cy - q)} ${f(cx)} ${f(cy - r)} Z`;
}
function sparkle(cx, cy, r, opacity = 1) {
  return `<g opacity="${opacity}"><circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r * 1.9)}" fill="url(#glow)"/>` +
    `<path d="${star(cx, cy, r)}" fill="#fffaf0"/><path d="${star(cx, cy, r * 0.5, 0.2)}" transform="rotate(45 ${f(cx)} ${f(cy)})" fill="#fffaf0"/></g>`;
}

// pearls
const pearls = equalArcAngles(PA, PB, 56).map((t) => {
  const x = CX + PA * Math.cos(t), y = CY + PB * Math.sin(t);
  return `<circle cx="${f(x)}" cy="${f(y)}" r="15" fill="url(#pearl)"/><ellipse cx="${f(x - 4.6)}" cy="${f(y - 5.4)}" rx="4.4" ry="3" fill="#fff" opacity=".9" transform="rotate(-35 ${f(x - 4.6)} ${f(y - 5.4)})"/>`;
}).join('');

// sunburst
const RAYS = 32;
let rays = '';
for (let i = 0; i < RAYS; i += 2) {
  const a0 = (i / RAYS) * 2 * Math.PI, a1 = ((i + 1) / RAYS) * 2 * Math.PI, R = 1200;
  rays += `<path d="M${CX} ${CY} L${f(CX + R * Math.cos(a0))} ${f(CY + R * Math.sin(a0))} L${f(CX + R * Math.cos(a1))} ${f(CY + R * Math.sin(a1))} Z"/>`;
}

// bow (centre x = 512, sits on the top of the frame)
const BOW_Y = CY - B + 6;
const bowLoop = `M506 ${BOW_Y + 6} C470 ${BOW_Y - 38} 418 ${BOW_Y - 62} 380 ${BOW_Y - 44} C344 ${BOW_Y - 26} 346 ${BOW_Y + 26} 388 ${BOW_Y + 40} C432 ${BOW_Y + 54} 482 ${BOW_Y + 24} 506 ${BOW_Y + 14} Z`;
const bowFold = `M500 ${BOW_Y + 8} C470 ${BOW_Y - 20} 430 ${BOW_Y - 34} 398 ${BOW_Y - 22}`;
const bowFold2 = `M500 ${BOW_Y + 14} C470 ${BOW_Y + 34} 430 ${BOW_Y + 40} 402 ${BOW_Y + 28}`;
const bowTail = `M500 ${BOW_Y + 18} C486 ${BOW_Y + 48} 470 ${BOW_Y + 70} 444 ${BOW_Y + 92} L470 ${BOW_Y + 100} C490 ${BOW_Y + 82} 506 ${BOW_Y + 58} 516 ${BOW_Y + 24} Z`;


function bowMarkup(shadow) {
  const fill = shadow ? '#1d040c' : 'url(#satin)', stroke = shadow ? 'none' : '#9c2f4d';
  const half = (mirror) => `<g${mirror ? ' transform="matrix(-1 0 0 1 1024 0)"' : ''}>
    <path d="${bowTail}" fill="${fill}" stroke="${stroke}" stroke-width="3" stroke-linejoin="round"/>
    <path d="${bowLoop}" fill="${fill}" stroke="${stroke}" stroke-width="3.5" stroke-linejoin="round"/>
    ${shadow ? '' : `<path d="${bowFold}" fill="none" stroke="#fff0f4" stroke-width="5" stroke-linecap="round" opacity=".8"/><path d="${bowFold2}" fill="none" stroke="#b44563" stroke-width="4" stroke-linecap="round" opacity=".5"/>`}
  </g>`;
  const knot = `<rect x="486" y="${BOW_Y - 14}" width="52" height="46" rx="16" fill="${fill}" stroke="${stroke}" stroke-width="3.5"/>` +
    (shadow ? '' : `<path d="M496 ${BOW_Y - 4} Q512 ${BOW_Y - 12} 528 ${BOW_Y - 4}" fill="none" stroke="#fff0f4" stroke-width="4" stroke-linecap="round" opacity=".85"/>`);
  const body = half(false) + half(true) + knot;
  return shadow ? `<g opacity=".45" filter="url(#soft6)" transform="translate(2 12)">${body}</g>` : `<g>${body}</g>`;
}

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${W}" width="${W}" height="${W}">
<defs>
  <radialGradient id="bg" cx="${CX}" cy="${CY - 40}" r="640" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#a22848"/><stop offset=".5" stop-color="#7a1c37"/><stop offset=".93" stop-color="#5e1226"/><stop offset="1" stop-color="#5e1226"/>
  </radialGradient>
  <radialGradient id="rayFade" cx="${CX}" cy="${CY}" r="600" gradientUnits="userSpaceOnUse">
    <stop offset="0.3" stop-color="#fff" stop-opacity="1"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </radialGradient>
  <mask id="rayMask"><rect width="${W}" height="${W}" fill="url(#rayFade)"/></mask>
  <radialGradient id="halo" cx="${CX}" cy="${CY}" r="470" gradientUnits="userSpaceOnUse">
    <stop offset=".55" stop-color="#ffcf8a" stop-opacity=".30"/><stop offset="1" stop-color="#ffcf8a" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="gold" x1="190" y1="130" x2="835" y2="960" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff6cc"/><stop offset=".22" stop-color="#ebc96f"/><stop offset=".5" stop-color="#c99b3a"/><stop offset=".74" stop-color="#8a601c"/><stop offset="1" stop-color="#f0d78f"/>
  </linearGradient>
  <linearGradient id="goldRev" x1="835" y1="960" x2="190" y2="130" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#fff0b8"/><stop offset=".4" stop-color="#d2a645"/><stop offset=".8" stop-color="#7a5316"/><stop offset="1" stop-color="#e8cb83"/>
  </linearGradient>
  <linearGradient id="glassFill" x1="${CX - GA}" y1="${CY - GB}" x2="${CX + GA}" y2="${CY + GB}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="${T.glass[0]}"/><stop offset=".5" stop-color="${T.glass[1]}"/><stop offset="1" stop-color="${T.glass[2]}"/>
  </linearGradient>
  <radialGradient id="glassEdge" cx="${CX}" cy="${CY}" r="${GB}" gradientUnits="userSpaceOnUse" gradientTransform="translate(${CX} ${CY}) scale(${GA / GB} 1) translate(${-CX} ${-CY})">
    <stop offset=".72" stop-color="#5a1230" stop-opacity="0"/><stop offset="1" stop-color="#5a1230" stop-opacity=".42"/>
  </radialGradient>
  <linearGradient id="spiralGold" x1="${CX - GA}" y1="${CY - GB}" x2="${CX + GA}" y2="${CY + GB}" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="${T.spiralFill[0]}"/><stop offset=".5" stop-color="${T.spiralFill[1]}"/><stop offset="1" stop-color="${T.spiralFill[2]}"/>
  </linearGradient>
  <linearGradient id="glare1" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".5"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
  <radialGradient id="pearl" cx=".36" cy=".32" r=".8"><stop offset="0" stop-color="#ffffff"/><stop offset=".5" stop-color="#fdf1dc"/><stop offset="1" stop-color="#cdb084"/></radialGradient>
  <radialGradient id="glow"><stop offset="0" stop-color="#fffbe8" stop-opacity=".95"/><stop offset=".35" stop-color="#ffe9a8" stop-opacity=".45"/><stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/></radialGradient>
  <linearGradient id="satin" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffd0dc"/><stop offset=".5" stop-color="#f29ab4"/><stop offset="1" stop-color="#d4607f"/></linearGradient>
  <radialGradient id="eyeGlow" cx="${f(eye[0])}" cy="${f(eye[1])}" r="250" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${T.eyeGlow[0]}" stop-opacity="${T.eyeGlow[1]}"/><stop offset="1" stop-color="${T.eyeGlow[0]}" stop-opacity="0"/></radialGradient>
  <filter id="soft6" x="-20%" y="-30%" width="140%" height="160%"><feGaussianBlur stdDeviation="6"/></filter>
  <filter id="soft3" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="3"/></filter>
  <clipPath id="glassClip"><ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}"/></clipPath>
  <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14"/></filter>
  <filter id="pearlShadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="1.5" dy="3" stdDeviation="2.2" flood-color="#3e2204" flood-opacity=".55"/></filter>
  <filter id="inner" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="9"/></filter>
</defs>

<rect width="${W}" height="${W}" fill="#5e1226"/>
<rect width="${W}" height="${W}" fill="url(#bg)"/>
<g mask="url(#rayMask)" fill="#ffd9a0" opacity=".085">${rays}</g>
<ellipse cx="${CX}" cy="${CY}" rx="440" ry="500" fill="url(#halo)"/>

<!-- mirror -->
<ellipse cx="${CX + 6}" cy="${CY + 26}" rx="${A}" ry="${B}" fill="#240510" opacity=".55" filter="url(#soft)"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A}" ry="${B}" fill="url(#gold)" stroke="#5e3f0c" stroke-width="3"/>
<ellipse cx="${CX}" cy="${CY}" rx="${A - 9}" ry="${B - 9}" fill="none" stroke="#fff6cc" stroke-width="3" opacity=".7"/>
<ellipse cx="${CX}" cy="${CY}" rx="${PA}" ry="${PB}" fill="none" stroke="#6a4510" stroke-width="40" opacity=".42"/>
<ellipse cx="${CX}" cy="${CY}" rx="${PA}" ry="${PB}" fill="none" stroke="#fff0b8" stroke-width="2" opacity=".35" transform="translate(-1.5 -1.5)"/>
<g filter="url(#pearlShadow)">${pearls}</g>
<path d="M${f(CX + (A - 22) * Math.cos(3.6))} ${f(CY + (B - 22) * Math.sin(3.6))} A${A - 22} ${B - 22} 0 0 1 ${f(CX + (A - 22) * Math.cos(4.55))} ${f(CY + (B - 22) * Math.sin(4.55))}" fill="none" stroke="#fffbe6" stroke-width="9" stroke-linecap="round" opacity=".55" filter="url(#soft3)"/>
<ellipse cx="${CX}" cy="${CY}" rx="${GA + 7}" ry="${GB + 7}" fill="url(#goldRev)" stroke="#4e330a" stroke-width="2.5"/>

<!-- glass -->
<ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="url(#glassFill)"/>
<g clip-path="url(#glassClip)">
  <ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="url(#glassEdge)"/>
  <ellipse cx="${CX}" cy="${CY}" rx="${GA - 4}" ry="${GB - 4}" fill="none" stroke="#4a0e24" stroke-opacity=".5" stroke-width="22" filter="url(#inner)"/>
  <rect x="${CX - GA}" y="${CY - GB}" width="${2 * GA}" height="${2 * GB}" fill="url(#eyeGlow)"/>
  <path d="${ribbon(placed, 1, 12)}" fill="#6b1830" opacity=".30" transform="translate(4 8)" filter="url(#inner)"/>
  <path d="${ribbon(placed, 1, T.edgeGrow)}" fill="${T.spiralEdge}"/>
  <path d="${ribbon(placed, 1, 0)}" fill="url(#spiralGold)"/>
  <path d="${ribbon(placed, 0.32, 0, -0.2)}" fill="#fffbe6" opacity=".75"/>
  <ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="none"/>
  <polygon points="${CX - 330},${CY - 60} ${CX - 110},${CY - 380} ${CX - 40},${CY - 380} ${CX - 300},${CY + 60}" fill="url(#glare1)" opacity=".55" transform="rotate(0)"/>
  <polygon points="${CX - 215},${CY + 150} ${CX + 20},${CY - 190} ${CX + 50},${CY - 190} ${CX - 185},${CY + 160}" fill="url(#glare1)" opacity=".28"/>
</g>
<ellipse cx="${CX}" cy="${CY}" rx="${GA}" ry="${GB}" fill="none" stroke="#fff3c4" stroke-opacity=".55" stroke-width="2"/>
${sparkle(CX + 112, CY + 150, 17, 0.9)}
${sparkle(CX + 52, CY + 232, 10, 0.8)}
${sparkle(eye[0], eye[1], 34)}

<!-- bow -->
${bowMarkup(true)}
${bowMarkup(false)}

<!-- stray sparkles -->
${sparkle(168, 250, 30, 0.95)}
${sparkle(868, 760, 22, 0.9)}
${sparkle(146, 770, 12, 0.8)}
${sparkle(884, 300, 14, 0.8)}
</svg>`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, 'icon.svg'), svg);
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 1 });
  await p.setViewportSize({ width: W, height: W });
  await p.setContent(`<!doctype html><html><head><style>html,body{margin:0;background:#5e1226}svg{display:block}</style></head><body>${svg}</body></html>`);
  await p.waitForTimeout(200);
  await p.screenshot({ path: path.join(OUT, 'icon-1024.png'), omitBackground: false, clip: { x: 0, y: 0, width: W, height: W } });
  await b.close();
  console.log('wrote', path.join(OUT, 'icon-1024.png'), 'outer radius', fitted.s, 'eye', f(eye[0]), f(eye[1]));
})().catch((e) => { console.error(e); process.exit(1); });
