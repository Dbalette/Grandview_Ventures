#!/usr/bin/env bash
# Archive Mirror Mirror and upload it to App Store Connect, in one command. It is the same route as
# Xcode's Product > Archive > Distribute App > App Store Connect > Upload, which is how Arizona Water Watch ships.
#
# Run it on a Mac that is signed in to Xcode (Settings > Accounts) with the Apple ID of team Y2HWD96TBZ.
# The first run creates the App ID and the signing assets for you, through automatic signing.
#
#   ./release.sh              bundle, archive, and upload to App Store Connect
#   ./release.sh --ipa-only   bundle, archive, and export an .ipa into build/export (no upload)
#
# Before the first upload, the app record must exist in App Store Connect with the bundle id
# com.grandviewventures.mirrormirror (see SUBMISSION.md, step 1).
set -euo pipefail

if [ "$(uname)" != "Darwin" ] || ! command -v xcodebuild > /dev/null; then
  echo "This needs a Mac with Xcode installed." >&2
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"
OPTIONS="$HERE/ExportOptions.plist"
rm -rf "$BUILD"
mkdir -p "$BUILD"

if [ "${1:-}" = "--ipa-only" ]; then
  OPTIONS="$BUILD/ExportOptions-ipa-only.plist"
  cp "$HERE/ExportOptions.plist" "$OPTIONS"
  /usr/libexec/PlistBuddy -c "Set :destination export" "$OPTIONS"
fi

echo "1/3  Bundling the web app, vision library and face model"
bash "$HERE/prepare.sh"

echo "2/3  Archiving the Release build"
xcodebuild archive \
  -project "$HERE/MirrorMirror.xcodeproj" -scheme MirrorMirror -configuration Release \
  -destination "generic/platform=iOS" \
  -archivePath "$BUILD/MirrorMirror.xcarchive" \
  -allowProvisioningUpdates

echo "3/3  Exporting ($(/usr/libexec/PlistBuddy -c 'Print :destination' "$OPTIONS"))"
xcodebuild -exportArchive \
  -archivePath "$BUILD/MirrorMirror.xcarchive" \
  -exportOptionsPlist "$OPTIONS" \
  -exportPath "$BUILD/export" \
  -allowProvisioningUpdates

if [ "${1:-}" = "--ipa-only" ]; then
  echo "Done. The .ipa is in $BUILD/export"
else
  echo "Uploaded. In App Store Connect, wait for the build to finish processing (TestFlight tab), attach it to the 1.0 version, and submit for review."
fi
