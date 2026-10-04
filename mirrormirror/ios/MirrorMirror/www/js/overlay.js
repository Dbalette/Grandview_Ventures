/* Drawing: the live outline on the camera preview, and the measurement lines on the captured still. */
import { PREVIEW_POINTS } from './landmarks.js';

const GOLD = '#e8cf8e';

/** Mirror a pixel point horizontally within a frame of the given width. */
const mirrorPt = (q, w, mirror) => (mirror ? { x: w - q.x, y: q.y } : q);

/** Live preview: a sparse constellation of gold dots, mirrored to match the mirrored video. */
export function drawPreview(ctx, pixelLandmarks, width, height, { mirror = true, good = false } = {}) {
  ctx.clearRect(0, 0, width, height);
  if (!pixelLandmarks) return;
  ctx.save();
  ctx.fillStyle = good ? GOLD : 'rgba(232, 207, 142, 0.75)';
  ctx.shadowColor = 'rgba(232, 207, 142, 0.9)';
  ctx.shadowBlur = good ? 6 : 0;
  const r = Math.max(1.2, Math.min(width, height) / 260);
  for (const i of PREVIEW_POINTS) {
    const q = mirrorPt(pixelLandmarks[i], width, mirror);
    ctx.beginPath();
    ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

/** Draw the captured still with every measurement line. Returns the scale used. */
export function drawStill(canvas, image, imgW, imgH, landmarks, result, { mirror = false, activeId = null, maxEdge = 1200, showMidline = true } = {}) {
  const s = Math.min(1, maxEdge / Math.max(imgW, imgH));
  const W = Math.round(imgW * s), H = Math.round(imgH * s);
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.clearRect(0, 0, W, H);
  if (mirror) { ctx.translate(W, 0); ctx.scale(-1, 1); }
  ctx.drawImage(image, 0, 0, W, H);
  ctx.restore();

  const P = (q) => mirrorPt({ x: q.x * s, y: q.y * s }, W, mirror);
  const lw = Math.max(1.5, W / 420);

  // Faint constellation so the eye reads "measured", not "decorated".
  ctx.save();
  ctx.fillStyle = 'rgba(255, 250, 235, 0.55)';
  for (const i of PREVIEW_POINTS) { const q = P(landmarks[i]); ctx.beginPath(); ctx.arc(q.x, q.y, lw * 0.8, 0, Math.PI * 2); ctx.fill(); }
  ctx.restore();

  // Midline for the symmetry reading.
  if (showMidline && result.symmetry && result.symmetry.midline) {
    const { p, d } = result.symmetry.midline;
    const a = P({ x: p.x - d.x * 2000, y: p.y - d.y * 2000 });
    const b = P({ x: p.x + d.x * 2000, y: p.y + d.y * 2000 });
    ctx.save();
    ctx.strokeStyle = 'rgba(232, 207, 142, 0.9)';
    ctx.setLineDash([lw * 4, lw * 4]);
    ctx.lineWidth = lw * 0.9;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    ctx.restore();
  }

  const all = result.allMetrics || [];
  const draw = (m, active) => {
    for (const seg of m.segments || []) {
      const a = P(seg.a), b = P(seg.b);
      ctx.save();
      ctx.lineCap = 'round';
      ctx.strokeStyle = m.color;
      ctx.globalAlpha = active ? 1 : (activeId ? 0.18 : 0.85);
      ctx.lineWidth = active ? lw * 2.4 : lw * 1.3;
      ctx.shadowColor = 'rgba(0,0,0,0.6)';
      ctx.shadowBlur = active ? lw * 3 : lw;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      // end ticks
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
      const nx = (-dy / L) * lw * (active ? 5 : 3), ny = (dx / L) * lw * (active ? 5 : 3);
      ctx.lineWidth = active ? lw * 1.6 : lw;
      ctx.beginPath(); ctx.moveTo(a.x - nx, a.y - ny); ctx.lineTo(a.x + nx, a.y + ny); ctx.moveTo(b.x - nx, b.y - ny); ctx.lineTo(b.x + nx, b.y + ny); ctx.stroke();
      ctx.restore();
      if (active && seg.label) {
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const text = `${seg.label}: ${seg.px.toFixed(0)} px`;
        ctx.save();
        const fs = Math.max(11, lw * 7);
        ctx.font = `${fs}px "Josefin Sans", "Segoe UI", sans-serif`;
        const tw = ctx.measureText(text).width + lw * 8;
        const th = fs + lw * 6;
        const tx = Math.min(Math.max(mx - tw / 2, 4), W - tw - 4);
        const ty = Math.min(Math.max(my - th - lw * 4, 4), H - th - 4);
        ctx.fillStyle = 'rgba(27, 18, 22, 0.82)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(tx, ty, tw, th, lw * 3); else ctx.rect(tx, ty, tw, th);
        ctx.fill();
        ctx.fillStyle = m.color;
        ctx.textBaseline = 'middle';
        ctx.fillText(text, tx + lw * 4, ty + th / 2);
        ctx.restore();
      }
    }
  };
  for (const m of all) if (m.id !== activeId) draw(m, false);
  const act = all.find((m) => m.id === activeId);
  if (act) draw(act, true);
  return { scale: s, width: W, height: H };
}
