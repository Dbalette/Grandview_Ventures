#!/usr/bin/env bash
# Dry run of release.sh with stand-in tools. It exercises the script's control flow, its success markers and its checks
# without Xcode, a signing identity or an Apple account, so a typo in the one script you run before a release is found early.
# CI runs it on a macOS runner with the system bash (3.2) and the real PlistBuddy. Run it yourself: bash tools/dry_run_release.sh
set -euo pipefail

IOS="$(cd "$(dirname "$0")/.." && pwd)"
WWW="$IOS/MirrorMirror/www"
TMP="$(mktemp -d)"
STUBS="$TMP/stubs"
trap 'rm -rf "$TMP" "$IOS/build"' EXIT
mkdir -p "$STUBS"

[ -f "$WWW/vendor/face_landmarker.task" ] || bash "$IOS/prepare.sh" > /dev/null

# A stand-in xcodebuild that produces what the real one would, and prints the markers release.sh looks for.
cat > "$STUBS/xcodebuild" <<'STUB'
#!/usr/bin/env bash
mode="$1"; shift
archive=""; options=""; export_path=""
while [ $# -gt 0 ]; do
  case "$1" in
    -archivePath) archive="$2" ;;
    -exportOptionsPlist) options="$2" ;;
    -exportPath) export_path="$2" ;;
  esac
  shift
done
if [ "$mode" = "archive" ]; then
  app="$archive/Products/Applications/MirrorMirror.app"
  mkdir -p "$app"
  cp -R "$MM_STUB_WWW" "$app/www"
  if [ -n "${MM_STUB_OMIT:-}" ]; then rm -f "$app/www/vendor/$MM_STUB_OMIT"; fi
  cp "$MM_STUB_PRIVACY" "$app/PrivacyInfo.xcprivacy"
  python3 - "$app/Info.plist" <<'PY'
import plistlib, sys
plistlib.dump({"CFBundleIdentifier": "com.grandviewventures.mirrormirror", "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1"}, open(sys.argv[1], "wb"))
PY
  echo "** ARCHIVE SUCCEEDED **"
elif [ "$mode" = "-exportArchive" ]; then
  destination="$(python3 -c "import plistlib,sys; print(plistlib.load(open(sys.argv[1],'rb')).get('destination','export'))" "$options")"
  if [ "$destination" = "upload" ]; then
    if [ "${MM_STUB_NO_UPLOAD_MARKER:-}" != "1" ]; then echo "Uploaded package is processing."; fi
  else
    mkdir -p "$export_path"
    python3 - "$export_path/MirrorMirror.ipa" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as z:
    z.writestr("Payload/MirrorMirror.app/embedded.mobileprovision", "stub")
PY
    echo "** EXPORT SUCCEEDED **"
  fi
else
  echo "stub xcodebuild: unexpected mode $mode" >&2; exit 2
fi
STUB
# A stand-in for `security cms -D -i`, which decodes a provisioning profile into a plist.
cat > "$STUBS/security" <<'STUB'
#!/usr/bin/env bash
cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>TeamIdentifier</key><array><string>${MM_STUB_TEAM:-Y2HWD96TBZ}</string></array></dict></plist>
PLIST
STUB
chmod +x "$STUBS/xcodebuild" "$STUBS/security"
# On a non-Mac the script's first check needs to see a Mac. On a Mac the stub is harmless.
printf '#!/bin/sh\necho Darwin\n' > "$STUBS/uname"; chmod +x "$STUBS/uname"

export MM_STUB_WWW="$WWW" MM_STUB_PRIVACY="$IOS/MirrorMirror/PrivacyInfo.xcprivacy" MM_SKIP_PREPARE=1

failures=0
expect() { # expect <description> <want: pass|fail> <grep pattern in output> <command...>
  local what="$1" want="$2" pattern="$3"; shift 3
  local out status=0
  out="$("$@" 2>&1)" || status=$?
  local ok=1
  if [ "$want" = "pass" ] && [ "$status" -ne 0 ]; then ok=0; fi
  if [ "$want" = "fail" ] && [ "$status" -eq 0 ]; then ok=0; fi
  if ! printf '%s' "$out" | grep -q -- "$pattern"; then ok=0; fi
  if [ "$ok" = 1 ]; then echo "PASS  $what"; else echo "FAIL  $what (exit $status; wanted $want and /$pattern/)"; printf '%s\n' "$out" | tail -8 | sed 's/^/      /'; failures=$((failures + 1)); fi
}

run_release() { PATH="$STUBS:$PATH" /bin/bash "$IOS/release.sh" "$@"; }

expect "export mode succeeds and confirms the team from the artifact" pass "signed for team Y2HWD96TBZ" run_release --ipa-only
expect "upload mode succeeds on the upload marker"                       pass "Uploaded. App Store Connect is processing" run_release
MM_STUB_TEAM=ABCDE12345 expect "export mode fails when the team is wrong"        fail "not Y2HWD96TBZ" run_release --ipa-only
MM_STUB_NO_UPLOAD_MARKER=1 expect "upload mode fails without the upload marker"  fail "Uploaded package is processing" run_release
MM_STUB_OMIT=face_landmarker.task expect "the archive check catches a missing model" fail "missing www/vendor/face_landmarker.task" run_release --ipa-only

if [ "$failures" -ne 0 ]; then echo "$failures dry-run check(s) failed"; exit 1; fi
echo "release.sh dry run: all checks passed"
