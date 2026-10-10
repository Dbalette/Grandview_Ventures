# Mirror Mirror icon options

Two finished App Store icons, each drawn as one SVG and rendered to a 1024 by 1024 PNG. They are **not wired into the app yet**: the app
still ships the earlier gold-oval-with-phi icon in `MirrorMirror/Assets.xcassets`.

| Option | Files |
|---|---|
| A. Blush glass (recommended: the lighter centre reads best at small sizes) | `blush/icon.svg`, `blush/icon-1024.png` |
| B. Dark glass (the Snow White magic mirror) | `magic/icon.svg`, `magic/icon-1024.png` |

`options.png` shows both large and at home-screen sizes on light and dark wallpapers.

**The drawing.** A 1950s vanity mirror: gold oval frame with a ring of pearls, a pink satin bow on top, a burgundy sunburst behind. Inside
the glass is an exact golden spiral, where the radius grows by phi every quarter turn, drawn as a tapered ribbon with a sparkle at its eye.

Both pass `tools/check_icon.py`: 1024 by 1024, opaque RGB, and plain background everywhere the iOS corner mask clips.

**Regenerate.** `node make_icon.cjs <outDir> blush` or `magic` (needs Playwright with Chromium). `ROTDEG`, `DIR`, `WMAX` and `NQ` change the
spiral's orientation, thickness and number of turns; `PRINT_FIT=1` lists the placements that fit.

**To adopt option A.** Copy `blush/icon-1024.png` over `../MirrorMirror/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png`, run
`python3 ../tools/check_icon.py`, rebuild, and regenerate the web icons in `../../icons` (they need rounded corners).
