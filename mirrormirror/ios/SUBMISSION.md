# Mirror Mirror on The Wall: getting it onto the App Store

This folder is a complete iOS app: a SwiftUI shell that serves the web app from the bundle through a
local URL scheme (`mirror://app/`), opens the front camera inside a `WKWebView`, and sells one
auto-renewing subscription through StoreKit 2. Free to download, three free readings, then
**Mirror Mirror Premium at US$0.99 a month** (product id `com.grandviewventures.mirrormirror.monthly`).

What follows is everything between this folder and the "Submit for Review" button, in order. Steps
marked **you** need your Apple ID, your Mac, or App Store Connect, which nobody else can do for you.

## 0. One-time setup (you, about 30 minutes)

1. **Apple Developer Program** membership on your Apple ID (developer.apple.com, US$99/year).
2. **Agreements**. In App Store Connect open *Business* (older accounts: *Agreements, Tax, and Banking*) and
   accept the **Paid Apps** agreement, then add bank account and tax forms. Subscriptions cannot be
   created, and the app cannot be submitted with one, until this shows *Active*.
3. **Sandbox tester**. App Store Connect > Users and Access > Sandbox > Testers > add a test Apple ID
   (any email you control). You will sign in with it on your test iPhone (Settings > App Store > Sandbox Account).

## 1. Create the app record (you, 5 minutes)

App Store Connect > My Apps > "+" > New App:

| Field | Value |
|---|---|
| Platform | iOS |
| Name | Mirror Mirror on The Wall |
| Primary language | English (U.S.) |
| Bundle ID | `com.grandviewventures.mirrormirror` (register it first under Certificates, Identifiers & Profiles > Identifiers, with the **In-App Purchase** capability ticked, or let Xcode automatic signing register it when you first build) |
| SKU | `mirrormirror-ios` |
| User access | Full |

If the name is taken, "Mirror Mirror: Golden Ratio" is the fallback; the bundle id can stay.

## 2. Create the subscription (you, 10 minutes)

App Store Connect > the app > *Monetization* > *Subscriptions* > create a **subscription group**:

* Group reference name: `Mirror Mirror Premium`

Inside the group, create the subscription:

| Field | Value |
|---|---|
| Reference name | Premium Monthly |
| Product ID | `com.grandviewventures.mirrormirror.monthly` (must match `StoreManager.productID` exactly) |
| Duration | 1 month |
| Price | US$0.99 (pick the US price; Apple fills in every other storefront) |
| Family Sharing | off |
| Localization (en-US) | Display name **Mirror Mirror Premium**; description **Unlimited readings with every line of the arithmetic.** |
| Review information | a screenshot of the paywall screen from your phone, and the note: *"Three readings are free; the paywall appears when you open the mirror a fourth time. Subscribe with a sandbox account; Restore purchases is on the same screen."* |
| Group localization | Group display name **Mirror Mirror Premium** |

Leave it in *Ready to Submit*. The first subscription in an app is submitted together with the first app
version, in the *In-App Purchases and Subscriptions* box on the version page (step 6).

## 3. Build and test on your iPhone (you + Xcode, 15 minutes)

```bash
git clone https://github.com/Dbalette/Grandview_Ventures.git
cd Grandview_Ventures
bash mirrormirror/ios/prepare.sh        # copies the web app into www/ and downloads the vision library + face model (about 40 MB, kept out of git)
open mirrormirror/ios/MirrorMirror.xcodeproj
```

In Xcode:

1. Select the **MirrorMirror** target > *Signing & Capabilities* > tick *Automatically manage signing* and pick your **Team**.
   If Xcode asks, add the **In-App Purchase** capability.
2. Plug in an iPhone (the simulator has no camera) and run. Allow the camera when asked.
3. Purchases are wired to the local StoreKit configuration file for testing: *Product > Scheme > Edit Scheme > Run > Options > StoreKit Configuration* should show `MirrorMirror.storekit` (the shared scheme already sets it). Take three readings; the fourth opens the paywall; tap Subscribe; the test purchase sheet appears without charging anything. *Debug > StoreKit > Manage Transactions* lets you refund and retry.
4. To test against the real sandbox instead, set the StoreKit Configuration back to *None* and sign in with the sandbox tester on the phone.
5. Once the app has an App Store id, put its URL in `AppConfig.swift` (`appStoreURL`); the web version uses it to point people to the app.

If the project refuses to open or build on your Xcode version, say so (paste the error); the project file was written by hand, not by Xcode, so it could not be compiled before it reached you.

## 4. Archive and upload (you, 5 minutes, or the GitHub Action)

**In Xcode:** set the device to *Any iOS Device (arm64)*, then *Product > Archive* > *Distribute App* > *App Store Connect* > *Upload*. Keep *Upload your app's symbols* and *Manage version and build number* ticked.

**Or from GitHub:** the workflow *Mirror Mirror - upload to TestFlight* (`.github/workflows/mirrormirror-testflight.yml`) does the same on a macOS runner. It needs six repository secrets, listed at the top of the file: an App Store Connect API key (id, issuer id, the .p8 file base64-encoded), your team id, and an Apple Distribution certificate exported as a .p12 with its password. Run it from the *Actions* tab.

Either way the build appears under *TestFlight* in App Store Connect after 10 to 30 minutes of processing. Install it through TestFlight on your phone and take one more reading before submitting.

## 5. Fill in the listing (you, 20 minutes)

App Store Connect > the app > *App Store* tab > *1.0 Prepare for Submission*.

**Screenshots** (6.9-inch iPhone set is required; take them on an iPhone 15/16 Pro Max or let Xcode's simulator show the app with a photo): the welcome screen, the live mirror with the gold constellation, the verdict dial, the ratio breakdown with a row opened, the symmetry panel, the paywall.

**Promotional text**: *The golden ratio, line by line.*

**Description** (the last paragraph is required by Apple for auto-renewing subscriptions):

> Mirror, mirror, on the wall, but this one shows its arithmetic.
>
> Mirror Mirror finds 478 points on your face with the front camera, measures the distances between them, and compares your proportions with the golden ratio (phi, 1.618), the classical canons of the sculptors, the modern experiments on what people actually prefer, and your own left-to-right symmetry. You get a score out of 100 and, underneath it, every formula: the pixels, the millimetres, the ideal, the deviation, the points.
>
> • The seven golden ratios of the face, with the working shown
> • Symmetry measured point by point against your facial axis
> • Second opinions: Leonardo's thirds and fifths, Farkas's canons, and the 2010 "new golden ratios"
> • Head-pose and expression coaching so the reading is fair
> • A comparison with the average face from published anthropometry and with the famous faces in the press
> • A shareable card
> • Everything happens on your phone. No photograph, measurement or score ever leaves it. No account.
>
> Three readings are free. Mirror Mirror Premium gives you unlimited readings for US$0.99 a month.
>
> Mirror Mirror Premium is an auto-renewing subscription of US$0.99 per month. Payment will be charged to your Apple ID account at the confirmation of purchase. The subscription automatically renews unless it is cancelled at least 24 hours before the end of the current period. Your account will be charged for renewal within 24 hours prior to the end of the current period. You can manage and cancel your subscriptions in your App Store account settings after purchase.
> Privacy Policy: https://dbalette.github.io/Grandview_Ventures/mirrormirror/privacy.html
> Terms of Use: https://dbalette.github.io/Grandview_Ventures/mirrormirror/terms.html

**Keywords**: `golden ratio,face,beauty,symmetry,phi,proportion,facial analysis,mirror,attractiveness,selfie`

**Support URL**: https://dbalette.github.io/Grandview_Ventures/mirrormirror/privacy.html
**Marketing URL**: https://dbalette.github.io/Grandview_Ventures/mirrormirror/
**Privacy Policy URL** (in *App Information*): https://dbalette.github.io/Grandview_Ventures/mirrormirror/privacy.html
**Category**: Entertainment (secondary: Lifestyle). **Age rating**: answer *None* to everything; it comes out 4+.
**License agreement**: keep Apple's standard EULA (the app and the description link to it).

**App Privacy** (*App Privacy* tab): *Data Not Collected*. The app has no server and no analytics; the camera frames are processed in memory on the device; the vision library pinned here (0.10.35) is the last release without Google's usage telemetry. Nothing is linked to the user or used for tracking.

## 6. Submit for review (you, 5 minutes)

On the 1.0 version page:

1. *Build*: pick the processed build.
2. *In-App Purchases and Subscriptions*: add **Premium Monthly**.
3. *App Review Information*: contact details, and these notes:

   > The whole app runs on the device: the front camera feeds an on-device face-landmark model (MediaPipe), the proportions are computed locally, nothing is uploaded and there is no account. Three readings are free; opening the mirror a fourth time shows the paywall for Mirror Mirror Premium (US$0.99/month, auto-renewing). Restore Purchases is on the paywall. The reading can also be taken from a photo ("Use a photo instead") if the reviewer prefers not to use the camera. The app makes no medical, health or psychological claims; the methodology page states that the golden ratio is not a validated measure of attractiveness.

4. *Version Release*: *Manually release this version* if you want to choose the day.
5. Export compliance is pre-answered (`ITSAppUsesNonExemptEncryption` is false in Info.plist).
6. **Submit for Review**. Typical turnaround is one to two days.

## If App Review pushes back

* **Guideline 4.2 (minimum functionality / "web wrapper")**: reply that the app's function is on-device machine-learning analysis of the live camera with native purchasing, that it works offline once installed, and that the web technology is the rendering layer. It is a real risk for any WebView app; the mitigation is the review note above and screenshots that show the camera and the arithmetic.
* **Guideline 3.1.2 (subscription terms)**: the paywall shows price, period, renewal terms, Privacy Policy, Terms of Use and Restore, and the description carries the required paragraph. If asked, point to them.
* **Guideline 5.1.1 (data use)**: the camera purpose string is in Info.plist; nothing is collected.
* **Face data**: no face data is stored, transmitted or used to identify anyone; say so if asked.

## Files in this folder

| Path | Purpose |
|---|---|
| `MirrorMirror.xcodeproj` | the Xcode project (one target, no dependencies, no CocoaPods) |
| `MirrorMirror/MirrorMirrorApp.swift`, `ContentView.swift` | SwiftUI entry point |
| `MirrorMirror/WebView.swift` | the WKWebView, the JavaScript bridge, camera permission, external links |
| `MirrorMirror/LocalSchemeHandler.swift` | serves `www/` at `mirror://app/` so modules, WebAssembly and the camera work as on https |
| `MirrorMirror/StoreManager.swift` | StoreKit 2: product, purchase, entitlement, restore, manage |
| `MirrorMirror/AppConfig.swift` | free-reading allowance, product id, App Store URL, bundled library paths injected as `window.MM_CONFIG` |
| `MirrorMirror/Info.plist` | camera purpose string, portrait only, no non-exempt encryption |
| `MirrorMirror/MirrorMirror.storekit` | local StoreKit configuration for testing purchases without App Store Connect |
| `MirrorMirror/www/` | the web app, copied by `prepare.sh`; `www/vendor/` (library + model) is downloaded by the same script and ignored by git |
| `prepare.sh` | run before building: syncs the web app and fetches the vision library and face model |
| `ExportOptions.plist` | export settings used by the GitHub workflow |
