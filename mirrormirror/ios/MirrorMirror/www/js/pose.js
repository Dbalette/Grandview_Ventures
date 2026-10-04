/* Head pose from the Face Landmarker, in degrees.
   yaw   > 0 : the subject has turned towards their own LEFT (the face points to the image's right)
   pitch > 0 : chin lifted (face points up)
   roll  > 0 : head tilted so the subject's left eye sits lower in the image
   The transformation matrix is the primary source; the landmarks are a fallback and a sign check. */
import { LM } from './landmarks.js';
import { deg, dist, clamp } from './geometry.js';

/** Angles from the 4x4 facial transformation matrix (flattened, column-major, as the Web API returns it). */
export function poseFromMatrix(data) {
  if (!data || data.length < 16) return null;
  // Columns of the rotation block: local x, y, z axes expressed in camera space.
  const xAxis = { x: data[0], y: data[1], z: data[2] };
  const zAxis = { x: data[8], y: data[9], z: data[10] };
  // Camera space is right-handed: +x right, +y up, +z towards the camera.
  const yaw = deg(Math.atan2(zAxis.x, zAxis.z));
  const pitch = deg(Math.atan2(zAxis.y, zAxis.z));
  const roll = -deg(Math.atan2(xAxis.y, xAxis.x));
  return { yaw, pitch, roll, source: 'matrix' };
}

/** Rough angles from the landmarks alone (pixel coordinates). Good enough to guide a user. */
export function poseFromLandmarks(p) {
  const nose = p[LM.NOSE_TIP];
  const r = p[LM.ZYGION_R], l = p[LM.ZYGION_L];
  const dR = Math.abs(nose.x - r.x), dL = Math.abs(l.x - nose.x);
  const yaw = deg(Math.asin(clamp((dR - dL) / (dR + dL || 1), -1, 1)));
  // Vertical: where the nose tip sits between the nasion and the chin. A frontal face puts it near 0.35 of the way down.
  const nas = p[LM.NASION], chin = p[LM.MENTON];
  const t = (nose.y - nas.y) / ((chin.y - nas.y) || 1);
  const pitch = deg(Math.asin(clamp((0.35 - t) * 2.0, -1, 1)));
  const a = p[LM.EXOCANTHION_R], b = p[LM.EXOCANTHION_L];
  const roll = deg(Math.atan2(b.y - a.y, b.x - a.x));
  return { yaw, pitch, roll, source: 'landmarks' };
}

/** Combine both estimates: magnitude from the matrix when present, sign agreement checked against the landmarks. */
export function estimatePose(pixelLandmarks, matrixData) {
  const fromLm = poseFromLandmarks(pixelLandmarks);
  const fromM = poseFromMatrix(matrixData);
  if (!fromM) return fromLm;
  // If the matrix and the landmarks disagree on the direction of a clear turn, trust the landmarks' sign.
  const fix = (m, l) => (Math.abs(l) > 6 && Math.sign(m) !== Math.sign(l) ? -m : m);
  return { yaw: fix(fromM.yaw, fromLm.yaw), pitch: fromM.pitch, roll: fix(fromM.roll, fromLm.roll), source: 'matrix+landmarks' };
}

export const POSE_LIMITS = { yaw: 7, pitch: 8, roll: 5, minFaceFrac: 0.22, maxFaceFrac: 0.95, margin: 0.015 };

/** Check that the face is frontal, level, large enough and inside the frame. */
export function checkPose(pose, pixelLandmarks, width, height, limits = POSE_LIMITS) {
  const faceW = dist(pixelLandmarks[LM.ZYGION_R], pixelLandmarks[LM.ZYGION_L]);
  const frac = faceW / Math.min(width, height);
  let inside = true;
  const mx = width * limits.margin, my = height * limits.margin;
  for (const q of pixelLandmarks) { if (q.x < mx || q.y < my || q.x > width - mx || q.y > height - my) { inside = false; break; } }
  const checks = {
    face: true,
    yaw: Math.abs(pose.yaw) <= limits.yaw,
    pitch: Math.abs(pose.pitch) <= limits.pitch,
    roll: Math.abs(pose.roll) <= limits.roll,
    size: frac >= limits.minFaceFrac && frac <= limits.maxFaceFrac && inside,
  };
  const ok = Object.values(checks).every(Boolean);
  let hint = 'Hold still…';
  if (!inside) hint = 'Bring your whole face into the mirror';
  else if (frac < limits.minFaceFrac) hint = 'Come a little closer';
  else if (frac > limits.maxFaceFrac) hint = 'A little further back, please';
  else if (!checks.yaw) hint = pose.yaw > 0 ? 'Turn a touch to your right' : 'Turn a touch to your left';
  else if (!checks.pitch) hint = pose.pitch > 0 ? 'Lower your chin a little' : 'Lift your chin a little';
  else if (!checks.roll) hint = 'Level your head';
  return { ok, checks, hint, faceFrac: frac, inside };
}
