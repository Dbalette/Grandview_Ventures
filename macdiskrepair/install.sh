#!/bin/bash
# Mac Disk Repair installer. Run on the Mac:  ./install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This tool targets macOS. Detected: $(uname -s)." >&2
  echo "You can still run the unit tests here with: python3 -m unittest discover -s tests" >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install it first: https://brew.sh" >&2
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Xcode Command Line Tools are required (for python3). Running: xcode-select --install"
  xcode-select --install || true
  echo "Re-run this installer once the tools finish installing." >&2
  exit 1
fi

echo "==> Installing Homebrew formulas from Brewfile"
brew bundle --file="$HERE/Brewfile"

PREFIX="$(brew --prefix)"
LINK="$PREFIX/bin/mdr"
echo "==> Linking $LINK -> $HERE/bin/mdr"
ln -sf "$HERE/bin/mdr" "$LINK"
chmod +x "$HERE/bin/mdr"

echo
echo "Installed. Next steps:"
echo "  mdr doctor          # verify tools"
echo "  mdr detect          # find the external SSD"
echo "  sudo mdr health diskN"
