#!/usr/bin/env bash
# Archive Mirror Mirror and upload it to App Store Connect, the way Arizona Water Watch ships (Arizona playbook, section 12).
# It is the same route as Xcode's Product > Archive > Distribute App > App Store Connect > Upload, in one command.
#
# Run it on a Mac that is signed in to Xcode (Settings > Accounts) with the Apple ID of team Y2HWD96TBZ. The first run
# registers the App ID and creates the signing assets through automatic signing.
#
#   ./release.sh --ipa-only   bundle, archive, export a signed .ipa locally and check the team. No account is contacted.
#   ./release.sh              bundle, archive, and upload to App Store Connect.
#
# Do the --ipa-only run first: it proves the signing chain before anything is uploaded (playbook 12.7, steps 5 and 6).
# The App Store Connect app record must exist for the bundle id before the upload (playbook 12.10); a missing record shows up
# as "Error Downloading App Information". Set MM_SKIP_PREPARE=1 to reuse an already bundled www/ folder.
#
# Hygiene from the playbook: xcodebuild output goes to log files and is never piped (a pipe hides a failed exit status),
# success is judged by the markers in the logs, and the archive is inspected before it is trusted.
set -euo pipefail

TEAM="Y2HWD96TBZ"
BUNDLE_ID="com.grandviewventures.mirrormirror"
PB="${PLISTBUDDY:-/usr/libexec/PlistBuddy}"

fail() { echo "FAILED: $*" >&2; exit 1; }

if [ "$(uname)" != "Darwin" ] || ! command -v xcodebuild > /dev/null; then
  fail "this needs a Mac with Xcode installed"
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"
OPTIONS="$HERE/ExportOptions.plist"
MODE="upload"
if [ "${1:-}" = "--ipa-only" ]; then MODE="export"; fi

# Run a command with all of its output in a log file. Only the error lines are shown if it fails.
run() {
  local log="$1"; shift
  if ! "$@" > "$log" 2>&1; then
    grep -E "error:|\*\* [A-Z ]+ FAILED \*\*" "$log" | head -20 >&2 || true
    fail "$1 did not succeed; the full log is $log"
  fi
}

rm -rf "$BUILD"
mkdir -p "$BUILD"

if [ "$MODE" = "export" ]; then
  OPTIONS="$BUILD/ExportOptions-ipa-only.plist"
  cp "$HERE/ExportOptions.plist" "$OPTIONS"
  $PB -c "Set :destination export" "$OPTIONS"
fi

echo "1/4  Bundling the web app, vision library and face model"
if [ "${MM_SKIP_PREPARE:-}" = "1" ]; then
  echo "     (skipped: MM_SKIP_PREPARE=1)"
else
  bash "$HERE/prepare.sh" > "$BUILD/prepare.log" 2>&1 || { tail -5 "$BUILD/prepare.log" >&2; fail "prepare.sh did not succeed; see $BUILD/prepare.log"; }
fi

echo "2/4  Archiving the Release build (log: build/archive.log)"
run "$BUILD/archive.log" xcodebuild archive \
  -project "$HERE/MirrorMirror.xcodeproj" -scheme MirrorMirror -configuration Release \
  -destination "generic/platform=iOS" \
  -archivePath "$BUILD/MirrorMirror.xcarchive" \
  -allowProvisioningUpdates
grep -q "\*\* ARCHIVE SUCCEEDED \*\*" "$BUILD/archive.log" || fail "no ARCHIVE SUCCEEDED marker in $BUILD/archive.log"

# An archive can report success with an empty Products folder, so look inside it before trusting it.
APP="$BUILD/MirrorMirror.xcarchive/Products/Applications/MirrorMirror.app"
for item in Info.plist PrivacyInfo.xcprivacy www/index.html www/vendor/face_landmarker.task www/vendor/tasks-vision/wasm/vision_wasm_internal.wasm; do
  [ -e "$APP/$item" ] || fail "the archive is missing $item; run without MM_SKIP_PREPARE, and check the target's resources"
done
echo "     $($PB -c 'Print :CFBundleIdentifier' "$APP/Info.plist") version $($PB -c 'Print :CFBundleShortVersionString' "$APP/Info.plist") build $($PB -c 'Print :CFBundleVersion' "$APP/Info.plist")"
[ "$($PB -c 'Print :CFBundleIdentifier' "$APP/Info.plist")" = "$BUNDLE_ID" ] || fail "the bundle id is not $BUNDLE_ID (it is frozen at the first upload)"

echo "3/4  Exporting, destination: $($PB -c 'Print :destination' "$OPTIONS") (log: build/export.log)"
run "$BUILD/export.log" xcodebuild -exportArchive \
  -archivePath "$BUILD/MirrorMirror.xcarchive" \
  -exportOptionsPlist "$OPTIONS" \
  -exportPath "$BUILD/export" \
  -allowProvisioningUpdates

if [ "$MODE" = "export" ]; then
  grep -q "\*\* EXPORT SUCCEEDED \*\*" "$BUILD/export.log" || fail "no EXPORT SUCCEEDED marker in $BUILD/export.log"
  IPA="$(ls "$BUILD"/export/*.ipa 2>/dev/null | head -1 || true)"
  [ -n "$IPA" ] || fail "the export produced no .ipa in $BUILD/export"
  echo "4/4  Checking the team from the exported artifact, not from the archive log"
  unzip -p "$IPA" 'Payload/*.app/embedded.mobileprovision' > "$BUILD/embedded.mobileprovision" || fail "no embedded.mobileprovision in the .ipa"
  security cms -D -i "$BUILD/embedded.mobileprovision" > "$BUILD/embedded.plist" || fail "could not decode the provisioning profile"
  GOT="$($PB -c 'Print :TeamIdentifier:0' "$BUILD/embedded.plist")"
  [ "$GOT" = "$TEAM" ] || fail "the exported app is signed for team $GOT, not $TEAM"
  echo "     signed for team $GOT. The signing chain is sound."
  echo "Done. The .ipa is in $BUILD/export. Next: ./release.sh (no flag) uploads it."
else
  grep -q "Uploaded package is processing" "$BUILD/export.log" || fail "no 'Uploaded package is processing' marker in $BUILD/export.log; the upload did not complete (an 'Error Downloading App Information' means the App Store Connect record is missing for $BUNDLE_ID)"
  echo "4/4  Uploaded. App Store Connect is processing the build."
  echo "     Now: open TestFlight in App Store Connect and read which build number it assigned. It silently auto-bumps a colliding number."
  echo "     Then set CURRENT_PROJECT_VERSION in the project to match what shipped, attach the build to the 1.0 version, and continue with PUBLISH.md."
fi
