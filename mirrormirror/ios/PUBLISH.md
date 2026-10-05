# Publishing Mirror Mirror on The Wall

This is the run sheet for taking the app from "builds" to "Waiting for Review". It follows section 12 of the Arizona Water Watch
playbook: the ArizonaExplained repository, branch `session/news-headline-and-chart-fixes`, file `docs/CLONE_PLAYBOOK.md`. Note that
`main` in that repository still has the older playbook without section 12. The app is free to download with three free readings, then
**Mirror Mirror Premium at US$0.99 a month** (product id `com.grandviewventures.mirrormirror.monthly`).

**Why this needs your computer.** The playbook is explicit that the web UI never carries the binary, and that the upload needs a live
Apple ID session inside Xcode on a Mac. App Store Connect records, metadata, screenshots and submission go through your signed-in
browser. A cloud session has neither, so steps 1 to 12 below run in a session on your Mac. The prompt for it is at the end.

## What is already verified

On a macOS runner with Xcode 16.4 (CI run on every push, no secrets needed): Debug build for the simulator and Release build for
iPhone hardware with no Swift warnings, an unsigned archive, the release script's dry run with stand-in tools, a numeric icon check,
a validator for the store text, and a launch in an iPhone 17 Pro simulator on iOS 26. The launch showed the page loading from
`mirror://app/` as a secure context with camera support, the bundled library and model loading with no network, and the Swift store
bridge answering. Also tested: 10 unit tests and a browser run against both the web and the iPhone configuration, which fails if any
request leaves the device.

**Not verified, because it needs a phone and your Apple ID:** the live camera on a real iPhone, a real or sandbox purchase, Restore,
the share sheet, the first upload, and every App Store Connect step.

## Decisions to settle first (consent is per action)

| Decision | Current default | Why it gates |
|---|---|---|
| Bundle id | `com.grandviewventures.mirrormirror` | Frozen at the first uploaded build |
| Price | free app, subscription US$0.99 a month | Yours to confirm; also the countries |
| Release | manual after approval (recommended) | Automatic release ships the moment it is approved |
| Public push of the support pages | merge this branch to main | Publishes the Pages URLs; poll `curl -sI` until 200 before pasting them |
| Where the source lives | public Grandview_Ventures repo | The playbook keeps app source in a private repo and only the pages here |
| Submit for Review | not yet | Irreversible |

## Order (playbook 12.7)

**0. Ground truth.** Check the name is free: `https://itunes.apple.com/search?term=Mirror%20Mirror%20on%20the%20Wall&entity=software&country=us`.
If it is taken, the fallback name is "Mirror Mirror: Golden Ratio"; the bundle id can stay.

**1. Bundle and test on a real iPhone.** Double-click `Open in Xcode.command`, run on your iPhone, and check the camera, the
three-reading paywall (the `.storekit` file lets you buy without being charged), Restore, and the share sheet.

**2. Prove signing offline.** `./release.sh --ipa-only` archives, exports a signed .ipa locally, and checks the team from the exported
artifact. It contacts no account. If it fails with "No profiles for ... were found", switch `ExportOptions.plist` to
`signingStyle manual` with an explicit `signingCertificate` and `provisioningProfiles` entry, as the playbook shows in 12.6.

**3. Create the App Store Connect record** (web only, there is no API). Apps, New App: platform iOS, name, English (U.S.), the bundle
id from the dropdown (it lists only registered App IDs; the first `--ipa-only` run registers it), SKU `mirrormirroronthewall`, full
access. Then re-open `/apps` and confirm it shows "Prepare for Submission".

**4. Create the subscription.** Monetization, Subscriptions, group `Mirror Mirror Premium`, product `com.grandviewventures.mirrormirror.monthly`
(reference name Premium Monthly), duration 1 month, price US$0.99, Family Sharing off, display name "Mirror Mirror Premium",
description "Unlimited readings with every line of the arithmetic.", and a screenshot of the paywall for review. It is submitted
together with the first version in step 12.

**5. Upload.** `./release.sh`. Success is the line `Uploaded package is processing`. App Store Connect silently bumps a colliding
build number, so read the number it assigned in TestFlight and set `CURRENT_PROJECT_VERSION` to match.

**6. Metadata.** Paste verbatim from `store/` (name, subtitle, promotional text, keywords, description). Check first with
`python3 store/validate_store_text.py`: it enforces the field limits and the family rule of no em dashes in any store field. After
each Save, reload the page and re-read the values; a filled form proves nothing. Support URL and Privacy Policy URL:
`https://dbalette.github.io/Grandview_Ventures/mirrormirror/privacy.html`. Marketing URL: the folder. There is no What's New on a
first release.

**7. Screenshots.** Ten distinct images, the family standard, on iPhone only (the binary is iPhone-only). Capture on your iPhone at
6.9 inch, 1320 by 2868, with your own face or a consenting person's, never a stranger or a public figure. Suggested set: welcome,
live mirror with the points and coaching, the score dial, the annotated face, the seven ratios with one row open, symmetry, the
classical canons, the comparison, the arithmetic, the paywall. Upload with `docs/tools/upload_shots.py` from the ArizonaExplained repo
(display type `APP_IPHONE_67` accepts 1320 by 2868). Check sizes with `sips -g pixelWidth -g pixelHeight`, and `md5` to prove they differ.

**8. App Information, age rating, App Privacy.** These lock when the first version is in review, so finish them now. Category
Entertainment, secondary Lifestyle. Age rating: every answer No, including "Social Media Disabled for Users Under 13"; it resolves
to 4+. Content rights: answer that the app does not contain third-party content only if the public-figure names are removed from the
comparison panel; otherwise say it does and confirm you have the rights to the published figures shown. App Privacy: "Data Not
Collected", Save, and then a separate Publish click. The app has no server and no analytics, bundles its library, model and fonts, and
the privacy manifest declares no tracking and no collected data.

**9. Pricing and availability.** The app is Free. Confirm the countries.

**10. App Review Information.** Contact fields, the notes from `store/review-notes.txt`, and **Sign-in required unchecked** (it
defaults to checked). Reload and re-read.

**11. Attach the build.** The Info.plist sets `ITSAppUsesNonExemptEncryption` to false, so there should be no "Missing Compliance". If
there is, the Manage questionnaire answer is "None of the algorithms mentioned above".

**12. Add for Review, then Submit.** Add the subscription to the version. "Add for Review" only opens a Draft Submission panel; its
"Submit for Review" button is the actual submission. "Waiting for Review" in the sidebar is the confirmation. Ask before pressing it.

## Review risks to know about

- **Guideline 4.2, web wrapper.** The reply: the app's function is on-device machine-learning analysis of the live camera with native
  purchasing, it works fully offline, and the web technology is the rendering layer.
- **Names of public figures in the comparison panel.** They quote scores the press published. If you would rather not carry that
  risk, anonymise them in `js/norms.js` and rebuild.
- **Face data.** Nothing is stored, sent or used to identify anyone. The camera purpose string and the privacy manifest say so.

## Files

| Path | Purpose |
|---|---|
| `release.sh`, `Open in Xcode.command` | one-command archive and upload from a Mac; double-click launcher |
| `tools/check_icon.py` | numeric icon check: 1024 by 1024, opaque, nothing but background where the iOS mask clips |
| `tools/dry_run_release.sh` | dry run of `release.sh` with stand-in tools (CI runs it with the system bash) |
| `store/*.txt`, `store/validate_store_text.py` | the App Store Connect text and its validator |
| `prepare.sh` | syncs the web app into `www/`, fetches the vision library, face model and licence notice (kept out of git) |
| `MirrorMirror/` | the SwiftUI shell: web view, local `mirror://` scheme handler, StoreKit 2, native share sheet, privacy manifest |
| `MirrorMirror/MirrorMirror.storekit` | local StoreKit configuration for testing purchases without being charged |
| `ExportOptions.plist` | export settings; automatic signing with the team Arizona ships under |
| `../licenses.html` | open-source notices shown in the app |

## Prompt for a session on your computer

Open Claude on your Mac in your clone of Grandview_Ventures (the desktop app, or `claude remote-control` in a terminal there), check out
`claude/affectionate-heisenberg-ydtblc`, and send:

> Publish Mirror Mirror to App Store review. Follow mirrormirror/ios/PUBLISH.md, and for the how use section 12 of docs/CLONE_PLAYBOOK.md
> in the ArizonaExplained repo on branch session/news-headline-and-chart-fixes. Do steps 0 to 12 in order. Use Xcode on this Mac for the
> upload and my real Chrome for App Store Connect. Ask me before each irreversible step: the bundle id, pricing, the public push of the
> support pages, and Submit for Review. Reload and re-read every App Store Connect field after saving. If you reach a login or a
> decision, stop and tell me.
