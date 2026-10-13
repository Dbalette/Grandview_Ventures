# driverescue

A careful, read-only-first toolkit for getting data off old or failing drives, built from a real
rescue of a 480 GB SSD with a damaged APFS file index and an `Input/output error`.

**What it does:** finds your drive, tells you in plain language whether it is damaged, copies your
files off in priority order with an exact progress bar, images the whole drive if you want a
second layer of safety, and checks the copy against the original.

**What it cannot do:** repair worn-out flash or a dead controller. Nothing can, from software.
It also never writes to the drive being rescued, and it never erases anything: wiping is a plan it
prints for you to read and run yourself (`refresh-plan`).

Pure Python 3.9+, no packages to install. macOS and Linux.

## Quick start

```bash
cd drive-rescue
python3 -m driverescue doctor        # is this computer ready? (tools, permissions)
python3 -m driverescue drives        # find the drive and its volumes
python3 -m driverescue check disk5   # read-only health check -> verdict + what to do next
```

## A typical rescue

1. **Check** the drive: `check disk5`. If it says *damage found*, do **not** run First Aid or any
   repair. Repairs write to the drive.
2. **Open it read-only** (macOS): `diskutil mount readOnly disk20s1`
3. **See what you are about to copy** and how big it is (reads folder names only):
   `rescue "/Volumes/EL Capitan/Users" ~/rescue --dry-run`
4. **Copy it.** Priority folders first (Desktop, Documents, Pictures, Movies, Music, Dropbox).
   The destination can be a folder, a mounted share, or another computer over SSH:
   `rescue "/Volumes/EL Capitan/Users" daniel@192.168.12.180:el-capitan-rescue/Users --skip-replaceable`
   - Exact progress bar, speed and ETA. If speed stays low for two minutes it tells you why that
     usually happens and what to check. Ctrl+C is safe; run it again and it resumes.
   - A bad sector inside a file costs you one block, not the file or the job: unreadable blocks are
     zero-filled and listed in `rescue-damaged.json`.
   - From a second terminal: `status --watch`
5. **Verify**: `verify "/Volumes/EL Capitan/Users" daniel@192.168.12.180:el-capitan-rescue/Users`
6. Optional, belt and braces: **image** the whole drive (`image disk5 /big/disk/drive.img`, needs raw
   access, see below) and **scan** it for weak areas (`scan disk5`).
7. Only when the copy is verified: `refresh-plan --drive disk5` prints the wipe-and-test plan that
   decides whether the drive is reusable for scratch work or should be replaced.

## Commands

| command | what it does | writes to the drive? |
|---|---|---|
| `drives` | list connected drives and volumes | no |
| `doctor` | check tools, permissions, Full Disk Access | no |
| `check TARGET` | SMART + read-only file system check, plain-language verdict | no |
| `scan TARGET` | read every byte once; map of unreadable/slow areas; resumable | no |
| `image TARGET FILE` | exact image with a map file; copies healthy areas first, then works gently on bad ones; resumable | no (writes only FILE) |
| `rescue SRC DEST` | file copy, priority order, exact progress, resumable, local or SSH | no |
| `verify SRC DEST` | confirm every file arrived at the right size | no |
| `status [--watch]` | progress of a running job, from another terminal | no |
| `refresh-plan` | prints the wipe-and-test plan; runs nothing | no |

`TARGET` is a drive id (`disk5`, `sdb`), a device path, a mount path, or (for testing) an image file.

## Safety rules built in

- Refuses to write an image onto the drive it is reading, and checks free space first.
- Refuses to read a drive whose volumes are still mounted unless you add `--allow-mounted`
  (or `--unmount` on macOS), so the computer is not writing while you read.
- Never overwrites an existing image; resumes only when the matching map file exists.
- `check` is advisory: a live check that could not run says so instead of calling the drive healthy.

## Raw drive access on macOS (scan, image)

Reading a whole drive needs administrator rights **and** your terminal app in
*System Settings > Privacy & Security > Full Disk Access* (then quit the terminal with Cmd+Q and
reopen it). `doctor` shows whether it is on. `rescue` copies files from a mounted drive and does
not need either. If macOS keeps refusing, connect the drive to a Linux computer and run the same
command there.

```bash
sudo "$(which python3)" -m driverescue scan disk5
```

## Files it keeps (default `~/driverescue-work`, change with `--workdir`)

`check-*.json` verdicts, `scan-*.json` scan reports, `status-*.json` live progress,
`rescue-errors.log` files that could not be opened, `rescue-damaged.json` files copied with
unreadable blocks.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite uses simulated drives (bad sectors, slow areas, flaky blocks), a stand-in for ssh, and the
verbatim `diskutil`/`fsck_apfs` output from the original rescue as fixtures.

## Known limits

- Developed and tested on Linux with simulated drives. The macOS `diskutil` parsing follows
  Apple's documented plist keys but has not been run against real hardware yet: if `drives` or
  `check` show gaps on your Mac, that is the first place to look.
- `rescue` copies file contents, names, times and permissions. It does not copy macOS extended
  attributes, resource forks or ACLs.
- SSH resume relies on GNU `find -printf` on the receiving side (any Linux box); against a Mac
  receiver it still copies, but re-sends everything on a re-run.
- SMART over USB depends on the adapter passing it through; `check` says so when it cannot read it.
