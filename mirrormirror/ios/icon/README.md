# Mirror Mirror icon options

Two finished App Store icons, each drawn as one SVG and rendered to a 1024 by 1024 PNG. They are **not wired into the app yet**: the app
still ships the earlier gold-oval-with-phi icon in `MirrorMirror/Assets.xcassets`.

| Option | Files |
|---|---|
| A. Wine and gold (recommended: it matches the colours inside the app) | `wine/icon.svg`, `wine/icon-1024.png` |
| B. Midnight and gold (a cooler, more corporate feel) | `navy/icon.svg`, `navy/icon-1024.png` |

`options.png` shows both large and at home-screen sizes on light and dark wallpapers.

**The drawing.** A gold oval mirror with a beaded bezel and one glint. The dark glass holds an exact golden spiral, where the radius
shrinks by phi every quarter turn, drawn over the golden-rectangle construction it comes from: the squares are cut from the left, top, right
and bottom in turn, and the spiral passes through their corners and ends on the rectangle's corner. Nothing else is on the canvas.

Both pass `tools/check_icon.py`: 1024 by 1024, opaque RGB, and plain background everywhere the iOS corner mask clips.

**Regenerate.** `node make_icon.cjs <outDir> wine` or `navy` (needs Playwright with Chromium). `ROT` (90 or 270) and `FLIP` (0 or 1) choose
which way the spiral turns, `NQ` how many quarter turns it draws, and `PRINT=1` lists where the eye lands for each choice.

**To adopt one.** Copy its `icon-1024.png` over `../MirrorMirror/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png`, run
`python3 ../tools/check_icon.py`, rebuild, and regenerate the web icons in `../../icons` (they need rounded corners).

An earlier, more decorative pair (pearl ring, satin bow, sparkles) is in git history at commit `fc566bb`.
