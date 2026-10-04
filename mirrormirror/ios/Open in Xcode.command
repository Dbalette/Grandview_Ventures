#!/bin/bash
# Double-click to bundle the web app, vision library and face model, then open the project in Xcode.
cd "$(dirname "$0")" || exit 1
bash ./prepare.sh && open MirrorMirror.xcodeproj
