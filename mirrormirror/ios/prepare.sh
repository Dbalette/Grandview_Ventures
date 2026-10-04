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
rsync -a --delete --exclude vendor --exclude tests --exclude node_modules --exclude ios --exclude package.json --exclude README.md --exclude '.*' "$WEB/" "$WWW/"

echo "2/3  Fetching @mediapipe/tasks-vision $VERSION (the last release without usage telemetry)"
TMP="$(mktemp -d)"
curl -fsSL "https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-$VERSION.tgz" | tar -xz -C "$TMP"
mkdir -p "$WWW/vendor/tasks-vision/wasm"
cp "$TMP/package/vision_bundle.mjs" "$WWW/vendor/tasks-vision/"
cp "$TMP/package/wasm/"* "$WWW/vendor/tasks-vision/wasm/"
rm -rf "$TMP"

echo "3/3  Fetching the face landmark model"
curl -fsSL "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task" -o "$WWW/vendor/face_landmarker.task"

du -sh "$WWW/vendor"
echo "Done. Open MirrorMirror.xcodeproj, set your Team under Signing, and run on a real iPhone (the simulator has no camera)."
