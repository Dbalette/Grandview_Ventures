# Mirror Mirror icon

**Installed: option B, midnight and gold.** It is the App Store icon (`MirrorMirror/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png`)
and the web app's icon set (`../icons`, with the tracked copy in `MirrorMirror/www/icons`). Option A, wine and gold, is kept here as the alternative.

| Option | Files |
|---|---|
| **B. Midnight and gold (installed)** | `navy/icon.svg`, `navy/icon-1024.png` |
| A. Wine and gold (the app's own colours) | `wine/icon.svg`, `wine/icon-1024.png` |

`options.png` shows both large and at home-screen sizes on light and dark wallpapers.

**The drawing.** A gold oval mirror with a beaded bezel and one glint. The dark glass holds an exact golden spiral, where the radius
shrinks by phi every quarter turn, drawn over the golden-rectangle construction it comes from: the squares are cut from the left, top, right
and bottom in turn, and the spiral passes through their corners and ends on the rectangle's corner. Nothing else is on the canvas.

**Checks.** `tools/check_icon.py` (CI runs it): 1024 by 1024, opaque RGB, and plain background everywhere the iOS corner mask clips.
The maskable web icon keeps the whole mirror inside the 80 percent circle Android may crop to.

**The web set.** `icon.svg` is a light version for the favicon, the manifest and the service worker's cache (no beads, no construction
lines, fewer curve points). `icon-192.png` and `icon-512.png` have rounded, transparent corners. `apple-touch-icon.png` and
`icon-maskable-512.png` are opaque squares, because iOS and Android apply their own masks.

**Regenerate.** `node make_icon.cjs <outDir> navy|wine [--web <iconsDir>]` (needs Playwright with Chromium). `ROT` (90 or 270) and `FLIP`
(0 or 1) choose which way the spiral turns, `NQ` how many quarter turns it draws, and `PRINT=1` lists where the eye lands for each choice.

**To change the installed icon.** Run the generator with `--web ../../icons` for the colourway you want, copy its `icon-1024.png` over
`AppIcon-1024.png`, run `python3 tools/check_icon.py`, copy `../icons` to `MirrorMirror/www/icons` (`prepare.sh` does that), and bump
`VERSION` in `sw.js` so installed copies of the web app refresh.

An earlier, more decorative pair (pearl ring, satin bow, sparkles) is in git history at commit `fc566bb`.
