#!/usr/bin/env bash
# Prepare the iOS app bundle: copy the web app into www/ and fetch the vision library and face model.
# Run from anywhere: ./mirrormirror/ios/prepare.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WEB="$HERE/.."
WWW="$HERE/MirrorMirror/www"
VERSION="0.10.35"

echo "1/3  Copying the web app into $WWW"
mkdir -p "$WWW"
# Replace everything except vendor/ (downloaded below). An explicit list keeps tests, node_modules and the iOS folder out of the app.
find "$WWW" -mindepth 1 -maxdepth 1 ! -name vendor -exec rm -rf {} +
for item in index.html methodology.html privacy.html terms.html licenses.html manifest.webmanifest sw.js css js icons; do
  cp -R "$WEB/$item" "$WWW/"
done

echo "2/3  Fetching @mediapipe/tasks-vision $VERSION (the last release without usage telemetry)"
TMP="$(mktemp -d)"
curl -fsSL "https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-$VERSION.tgz" | tar -xz -C "$TMP"
mkdir -p "$WWW/vendor/tasks-vision/wasm"
cp "$TMP/package/vision_bundle.mjs" "$WWW/vendor/tasks-vision/"
cp "$TMP/package/wasm/"* "$WWW/vendor/tasks-vision/wasm/"
rm -rf "$TMP"

echo "3/3  Fetching the face landmark model and the MediaPipe licence notice"
curl -fsSL "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" -o "$WWW/vendor/face_landmarker.task"

curl -fsSL "https://raw.githubusercontent.com/google-ai-edge/mediapipe/master/LICENSE" -o "$WWW/vendor/LICENSE-MediaPipe.txt"

du -sh "$WWW/vendor"
echo "Done. Open MirrorMirror.xcodeproj, set your Team under Signing, and run on a real iPhone (the simulator has no camera)."
