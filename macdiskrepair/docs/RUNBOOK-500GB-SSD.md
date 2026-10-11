# Runbook: the old 500 GB USB SSD with corrupted blocks

Written for the exact case: an old 500 GB flash disk in a USB enclosure,
plugged into a Mac, with some blocks that fail to read.

## 0. Before you start

* You need a **healthy destination with at least 510 GB free** for the image
  (an external HDD, a NAS share, or free space on the Mac). The image is a raw
  copy, so it is as large as the disk.
* Budget time. Over USB 3 a 500 GB scan runs about 30 to 90 minutes. The
  ddrescue first pass takes about the same; the retry pass on the bad regions
  can take hours if the drive stalls on them. The remap takes seconds.
* Do not run First Aid in Disk Utility yet. Repairs write metadata; on a disk
  with unreadable blocks that can make recovery worse. Image first.

## 0b. Give Terminal Full Disk Access

System Settings > Privacy & Security > Full Disk Access > turn on Terminal,
then quit and reopen Terminal. Without it every raw read fails with
`Operation not permitted`, even with sudo.

## 1. Install and detect

```bash
cd macdiskrepair && ./install.sh
mdr doctor
mdr detect
```

Note the identifier (we will say `disk4`). Identifiers can change every time the
disk is re-plugged; always re-run `mdr detect`.

## 2. Health, read-only

```bash
sudo mdr health disk4 --workdir ~/mdr-work
```

Expect `SMART not readable` on a USB 3 enclosure; that is macOS, not the drive.
If you have a Thunderbolt or USB4 enclosure, or can put the SSD inside a Mac
with a SATA bay, SMART will answer and the grade gets much better evidence.

## 3. Surface scan, read-only

```bash
diskutil unmountDisk disk4
sudo mdr scan disk4 --workdir ~/mdr-work
```

Ctrl-C pauses; the same command resumes. Output: `~/mdr-work/disk4.badmap.json`
with exact byte offsets and LBAs of every unreadable block.

## 4. Rescue image

```bash
sudo mdr rescue disk4 --to /Volumes/Backup/disk4.img --workdir ~/mdr-work --execute
```

Pass 1 (`-n`) copies everything readable and skips the trouble spots. Pass 2
(`-r3`) returns to those spots three times. If the drive disappears mid-way
(old SSDs do), re-plug it, re-run `mdr detect` to get the new identifier, and
re-run the same command; the mapfile resumes.

## 5. Repair the copy and pull your files

```bash
sudo mdr repair --image /Volumes/Backup/disk4.img --execute
hdiutil attach /Volumes/Backup/disk4.img       # now it mounts like a disk
```

Copy what matters off the mounted image. If the filesystem is too damaged to
mount, run `sudo photorec /Volumes/Backup/disk4.img` (from `testdisk`) to carve
files out of the image, or `sudo testdisk` to rebuild the partition table.
Work on the image, not the sick disk.

## 6. Remap the bad blocks on the SSD

```bash
sudo mdr remap disk4 --workdir ~/mdr-work --image /Volumes/Backup/disk4.img --execute
```

Writes 512- or 4096-byte zero blocks over each bad LBA plus one neighbour on
each side, then reads them back. The result tells you whether the controller
retired the bad pages. If `still bad` is zero, continue. If not, the drive has
no spare area left: stop here, keep the image, recycle the SSD.

## 7. Repair the original

```bash
sudo mdr repair disk4 --workdir ~/mdr-work --execute
```

If repair fails even after a clean remap, the last resort is a fresh format:
`diskutil eraseDisk APFS Rescued disk4`. On an SSD that also issues TRIM over
the whole LBA range, which lets the controller rebuild its mapping. Then copy
the files back from the image.

## 8. Report

```bash
mdr report --workdir ~/mdr-work
```

`~/mdr-work/disk4.report.md` holds the grade, the evidence and the exact LBAs.
That file is your before/after proof; keep the `health` output from step 2 as
the "before".

## Interpreting the grade for this drive

* Pending/offline-uncorrectable in SMART (if visible) or a small bad map that
  clears fully after remap: grade B or C. Usable for non-critical data.
* Bad map in the thousands of blocks, or blocks that stay bad after remap:
  grade D or F. Its spare pool is exhausted. Retire it.
