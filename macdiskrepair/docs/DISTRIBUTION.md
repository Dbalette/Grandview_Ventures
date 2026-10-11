# Distribution plan: why not the Mac App Store, and what to do instead

Requested: submit Mac Disk Repair to App Review at $9.99 with ten screenshots
showing the 500 GB SSD before and after.

## Why the Mac App Store cannot take this app as built

1. **Sandbox.** Mac App Store apps must adopt the App Sandbox. A sandboxed app
   cannot open `/dev/rdiskN`, cannot run `sudo`, and cannot call `diskutil
   repairDisk` or `hdiutil attach` with raw-image keys. Every useful thing
   `mdr` does is forbidden.
2. **Privilege.** Reading and writing raw devices needs root. App Store apps
   may not install privileged helpers via `SMJobBless` for this purpose, and
   App Review rejects "requires Terminal and sudo" workflows.
3. **Licensing.** `ddrescue`, `testdisk` and `smartmontools` are GPL. Bundling
   GPL binaries inside an App Store app conflicts with the App Store terms;
   Homebrew installs them on the user's machine instead, which the App Store
   does not allow an app to require.
4. **Form factor.** App Review guideline 4.2 rejects apps that are a thin
   wrapper around command-line tools. This is a command-line tool.

So the $9.99 App Store listing is not a path. There are three paths that work.

## Path A (recommended): Developer ID app outside the App Store, paid via Paddle or Gumroad

* Build a small SwiftUI shell that bundles `mdr` and the Homebrew tools under
  `Contents/Resources`, signed with a **Developer ID Application** certificate
  and **notarized** (`xcrun notarytool submit --wait`, then `stapler staple`).
* Privileged work runs through a `SMAppService` daemon (macOS 13+) or an
  `osascript -e 'do shell script ... with administrator privileges'` prompt.
* Price $9.99 with a license key from Paddle (handles VAT/sales tax as merchant
  of record) or Gumroad. Trial: `health` and `scan` free, `rescue`/`remap`/`repair` paid.
* Support and privacy page: `macdiskrepair/privacy.html` in this repo, same
  pattern as the Water Watch apps.

## Path B: Homebrew tap, free, donations

```
brew tap dbalette/tools
brew install mdr
```

A tap formula pointing at this repo, depending on `smartmontools`, `ddrescue`,
`testdisk`. Zero review, zero fees, no payment.

## Path C: App Store "companion" (read-only)

A sandboxed SwiftUI app that only shows `diskutil info -plist` data, the
`badmap.json`/`report.md` produced by `mdr`, and sells for $9.99 as a report
viewer and guide. Allowed, but it cannot scan, image or repair, so it must be
described honestly as a companion.

## Screenshots and "before/after" proof

The before/after evidence is produced by the tool itself on the Mac:

1. `sudo mdr health disk4 --workdir ~/mdr-work` output before anything (screenshot 1-2).
2. `sudo mdr scan` progress and the final bad-block count (3-4).
3. `mdr rescue` pass plan and ddrescue's finished summary (5-6).
4. `mdr remap` result: attempted / readable after / still bad (7).
5. `mdr repair` on the original: verify OK (8).
6. `mdr report` grade before vs after (9-10).

Those must be captured on the Mac the SSD is plugged into. Nothing about the
drive is visible from a cloud build session, so no screenshot was fabricated here.

## On the "Arizona Water Watch playbook"

No playbook exists in this repository; only `arizona/privacy.html` and the
sibling support/privacy pages. The folder `/Users/daniel/Random App Projects`
lives on the Mac and is not reachable from the cloud session. If that playbook
is committed to the repo (or pasted into a session), its App Store Connect
steps can be adapted for Path C above; Paths A and B do not use App Store
Connect at all.
