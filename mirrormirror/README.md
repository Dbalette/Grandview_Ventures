# Mirror Mirror on The Wall

A magic mirror that answers in mathematics. It finds 478 landmarks on a face with the phone's front
camera (MediaPipe Face Landmarker, on device), measures the distances between them, and compares the
proportions with the golden ratio, the neoclassical canons, modern preference studies and the face's
own symmetry. It gives a score out of 100 and shows every formula behind it.

* **Web app**: this folder. Works on any phone browser over https (the camera needs a secure page).
  On GitHub Pages: `https://dbalette.github.io/Grandview_Ventures/mirrormirror/`
* **iOS app**: `ios/`, a SwiftUI + WKWebView wrapper with a StoreKit 2 subscription. See `ios/SUBMISSION.md`.
* **The math**: `methodology.html`, with sources. The engine is `js/phi.js`.

## How it works

1. `js/app.js` opens the front camera, runs the Face Landmarker in VIDEO mode, and coaches the pose
   (yaw, pitch, roll from the model's transformation matrix) and expression (smile, open jaw, from the
   blendshapes). A reading averages about a second of frames (median per landmark).
2. `js/hairline.js` walks up the forehead from the mesh's top point until the skin tone gives way to hair,
   because the mesh itself stops short of the hairline.
3. `js/phi.js` measures the named distances and scores seven golden ratios (ideal 1.618), six classical
   canons, two "modern" ratios (Pallett 2010) and bilateral symmetry. Each ratio scores
   `100 × (1 − |measured − ideal| / ideal)`; symmetry scores `100 − 2.5 × asymmetry%`; the headline is
   80% golden ratios + 20% symmetry.
4. `js/ui.js` renders the dial, the annotated still, the itemised breakdown with the working in pixels
   and millimetres (scaled from the iris, 11.7 mm), the second opinions, the comparison with Farkas's
   average faces and the published celebrity scores, and the shareable card.
5. `js/paywall.js` counts free readings (three) and talks to the native store when the page runs
   inside the iOS app.

Nothing leaves the device. The vision library is pinned to `@mediapipe/tasks-vision@0.10.35`, the last
release without usage telemetry. The iPhone app bundles the library, the face model and the fonts and
makes no network request of its own; the web version fetches the library and model once and caches them.

## Run it locally

```bash
cd mirrormirror
npx http-server . -p 8080 -c-1      # then open http://localhost:8080 (localhost counts as secure)
```

## Tests

```bash
cd mirrormirror
npm install                          # playwright + the pinned vision library, for the browser test
npm test                             # engine unit tests (node:test)
npm run e2e -- --video path/to/face.y4m --photo path/to/face.jpg
# the iPhone configuration: serve the bundle, block and count every request that leaves localhost
bash ios/prepare.sh && npm run e2e -- --bundled ios/MirrorMirror/www --video path/to/face.y4m --photo path/to/face.jpg
```

The end-to-end test serves the app, feeds Chromium a fake front camera from a `.y4m` file (make one
with `ffmpeg -loop 1 -i face.jpg -t 2 -r 15 -vf "scale=480:640:force_original_aspect_ratio=increase,crop=480:640,format=yuv420p" face.y4m`),
consults the mirror, uploads a photo, exercises the paywall, and writes screenshots to `tests/out/`.
Set `MM_VISION_DIR` and `MM_MODEL_PATH` to use local copies of the library and model, and `MM_CHROMIUM` to use a Chromium you already have (otherwise run `npx playwright install chromium` once).

The iOS app is compiled and smoke-tested on a macOS runner by `.github/workflows/mirrormirror-ios-build.yml`
(unsigned, no secrets): Debug for the simulator, Release for iPhone hardware, then it installs the app in
the simulator, launches it, and reads the page's console through a debug-only bridge to confirm the page is
a secure context, the bundled library and model load, and the store bridge answers.

## Layout

```
index.html  methodology.html  privacy.html  terms.html  licenses.html  manifest.webmanifest  sw.js
css/style.css  css/fonts/
js/  app.js  ui.js  phi.js  norms.js  landmarks.js  geometry.js  pose.js  overlay.js  hairline.js  paywall.js
icons/  tests/  ios/
```
