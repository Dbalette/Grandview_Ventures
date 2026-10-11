# Mac Disk Repair (`mdr`)

Assess the health of a failing external disk on macOS, rescue its data, force the
SSD to retire its unreadable blocks, repair the filesystem, and produce a graded
report. Built on macOS's own `diskutil`/`hdiutil`/`fsck_*` plus Homebrew's
`smartmontools`, `ddrescue`, `testdisk`, `f3`, `pv` and `gptfdisk`.

It is a command-line tool. It must run **on the Mac the disk is plugged into**,
with `sudo` for anything that touches the raw device.

## Install (on the Mac)

```bash
git clone https://github.com/dbalette/grandview_ventures.git
cd grandview_ventures/macdiskrepair
./install.sh            # brew bundle + links `mdr` into $(brew --prefix)/bin
mdr doctor
```

## The sequence for a disk with corrupted blocks

Order matters. Reads first, writes last, and never write to the sick disk before
its contents are safely imaged somewhere else.

```bash
mdr detect                                   # 1. find it (say it is disk4)
sudo mdr health disk4 --workdir ~/mdr-work   # 2. SMART + read-only verify, graded
diskutil unmountDisk disk4
sudo mdr scan disk4 --workdir ~/mdr-work     # 3. read-only surface scan -> exact bad-block map (resumable)
sudo mdr rescue disk4 --to /Volumes/Backup/disk4.img --workdir ~/mdr-work --execute   # 4. ddrescue image, 2 passes
sudo mdr repair --image /Volumes/Backup/disk4.img --execute                           # 5. fix the COPY, mount it, take your files
sudo mdr remap disk4 --workdir ~/mdr-work --image /Volumes/Backup/disk4.img --execute # 6. zero-fill bad LBAs -> controller retires them
sudo mdr repair disk4 --workdir ~/mdr-work --execute                                  # 7. fix the filesystem on the original
mdr report --workdir ~/mdr-work              # 8. Markdown + JSON report with a grade A-F
```

Or run it all with pauses: `sudo mdr revive disk4 --workdir ~/mdr-work --execute`.
Without `--execute` every command is a dry run that prints what it would do.

## What each step does, and why

| Step | Reads/Writes | Tool underneath | Why |
|---|---|---|---|
| `health` | reads | `smartctl -j -a`, `diskutil verifyDisk/verifyVolume` | Firmware's own opinion plus a metadata check, no risk. |
| `scan` | reads | raw `/dev/rdiskN` reads, bisected on I/O error | Finds the exact LBAs that fail, not just "something is wrong". Resumable. |
| `rescue` | reads source, writes image | `ddrescue -n` then `-r3` with a mapfile | Copies the good 99.99% first, retries the bad parts after. The mapfile makes it resumable. |
| `repair --image` | writes to the image | `hdiutil attach -nomount`, `diskutil repairVolume` | Repair the copy, keep the original untouched until your files are out. |
| `remap` | writes zeros over bad LBAs only | `pwrite` on `/dev/rdiskN`, then re-read | Flash cannot be fixed; the controller retires the page on WRITE and points the LBA at a spare. |
| `repair` | writes metadata | `diskutil repairDisk/repairVolume` | After remap, the filesystem can be made consistent again. |
| `report` | none | | Grade and evidence in one file. |

## Grades

| Grade | Meaning |
|---|---|
| A | Healthy. No defects found. |
| B | Serviceable. Minor wear or isolated, remapped defects. |
| C | Degraded. Unreadable blocks present; controller still has spare area. Non-critical use only. |
| D | Failing. Many unreadable blocks or remap did not clear them. Retire after rescue. |
| F | Dead or dying. SMART failed or large unreadable regions. |

## First-run requirement: Full Disk Access

macOS blocks raw device reads (`/dev/rdiskN`) even under `sudo` until the
terminal app has Full Disk Access. The symptom is `Operation not permitted`
(errno 1). Grant it once: System Settings > Privacy & Security > Full Disk
Access > enable Terminal, then quit and reopen Terminal.

## Honest limits

* **SMART over USB 3.x is normally unavailable on macOS.** The kernel exposes no
  SCSI pass-through for USB mass storage, so `smartctl` only reaches internal
  SATA/NVMe, Thunderbolt and USB4 devices. `mdr` tries `-d sat`, `-d sat,12`,
  `-d nvme` and the JMicron/ASMedia/Realtek NVMe bridge types, then says so
  plainly. The surface scan does not need SMART.
* **Remap only works while the drive has spare area.** If blocks still fail after
  the zero write, the SSD is out of spares and should be retired.
* **Data in a bad block is gone.** Rescue first; `remap` refuses to run without a
  full-size image unless you pass `--no-image-i-accept-data-loss`.
* **Not a Mac App Store app.** It needs `sudo`, raw device access and GPL tools,
  all of which the App Store sandbox forbids. See `docs/DISTRIBUTION.md`.

## Safety model

Every write path checks that the target is a whole disk, external, not the boot
disk, unmounted, and asks you to type the identifier back. Read-only commands
never open the device for writing.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests run on any OS: they exercise plist/JSON/mapfile parsing, the scan
bisection and resume logic, remap verification and the grading, against an
in-memory fake disk and recorded fixtures.

## Layout

```
bin/mdr            entry point
mdr/cli.py         subcommands
mdr/diskutil.py    diskutil/hdiutil wrappers (plist)
mdr/smart.py       smartctl JSON parsing and findings
mdr/surface.py     resumable surface scan -> badmap.json
mdr/rescue.py      ddrescue pass plan and mapfile parsing
mdr/fsrepair.py    verify/repair through diskutil
mdr/remap.py       zero-fill + verify of bad LBAs
mdr/report.py      grading and Markdown/JSON report
mdr/safety.py      guard rails
docs/              runbook, references, distribution plan
```
