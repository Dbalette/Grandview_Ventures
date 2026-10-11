# References and research notes

Collected 2026-10-11 while building Mac Disk Repair. The Homebrew JSON API
(formulae.brew.sh) was not reachable from the build environment, so formula
versions below come from the formula pages as surfaced by web search and may
have moved on.

## Homebrew formulas used (Brewfile)

| Formula | Stable (as found) | Role | Source |
|---|---|---|---|
| smartmontools | 7.5 | `smartctl -j -a` SMART readout, SAT/NVMe bridge device types | https://formulae.brew.sh/formula/smartmontools |
| ddrescue | 1.30 | fault-tolerant imaging with resumable mapfile | https://formulae.brew.sh/formula/ddrescue |
| testdisk | 7.2 | TestDisk partition rebuild, PhotoRec file carving | https://formulae.brew.sh/formula/testdisk |
| f3 | (formula exists; version not confirmed) | `f3probe` true-capacity test for flash | project README |
| pv | | progress for pipelines | |
| gptfdisk | | `sgdisk` GPT backup/inspect | |

## SMART on USB under macOS

* smartmontools USB wiki: a USB bridge must offer ATA pass-through and the OS
  needs a SCSI pass-through interface; macOS lacks one for USB mass storage.
  https://www.smartmontools.org/wiki/USB
* MacPorts users thread (May 2024): smartctl does not work on USB drives on
  macOS without a third-party kernel driver; Thunderbolt enclosures work.
  https://lists.macports.org/pipermail/macports-users/2024-May/052729.html
* Eclectic Light, "Which external drives have Trim and SMART support?" (2024):
  macOS exposes SMART over Thunderbolt/USB4, not USB 3.x.
  https://eclecticlight.co/2024/04/09/which-external-drives-have-trim-and-smart-support/
* smartmontools ticket 25 on Mac OS X USB SMART (historical).
  https://smartmontools.org/ticket/25

## Filesystem checks on macOS

* Eclectic Light, "Last Week on My Mac: Giving a fsck" (2025): `fsck_apfs -n`
  read-only, `-y` repair, `-S` skip snapshots, `-q` quick.
  https://eclecticlight.co/2025/03/23/last-week-on-my-mac-giving-a-fsck/
* Eclectic Light, "APFS: Command tools" (2024).
  https://eclecticlight.co/2024/04/22/apfs-command-tools/
* Eclectic Light, "Access and repair a broken disk image" (2026):
  `hdiutil attach -nomount -noverify`, then `fsck_apfs -y` on the inner volume.
  https://eclecticlight.co/2026/03/25/access-and-repair-a-broken-disk-image/
* AppleInsider on fsck for HFS+: `fsck -fy /dev/diskNsM`; volumes must be unmounted.
  https://appleinsider.com/inside/macos/tips/how-to-use-fsck-to-check-and-repair-macos-disks
* iBoysoft diskutil reference: verifyDisk/repairDisk, verifyVolume/repairVolume.
  https://iboysoft.com/wiki/diskutil.html

## ddrescue

* Man page: `-n` no scrape, `-r N` retry passes, `-R` reverse, `-A` try again,
  `-b` sector size. Mapfile states: `?` non-tried, `*` non-trimmed,
  `/` non-scraped, `-` bad sector, `+` finished.
  https://man.archlinux.org/man/ddrescue.1.en
* Wikipedia overview of the copy/trim/scrape algorithm.
  https://en.wikipedia.org/wiki/Ddrescue

## Forcing reallocation by writing

* Level1Techs primer on bad sectors: a drive remaps a failing sector when it is
  WRITTEN, not read; write zeros to the LBA (and often its neighbours) after
  backing up. https://forum.level1techs.com/t/mechanical-drive-bad-sectors-the-drive-is-not-always-dead-a-primer/255113
* LKML thread on reallocation during write vs read (2003).
  https://lkml.iu.edu/hypermail/linux/kernel/0310.3/0582.html
* For SSDs the flash translation layer handles the remap; NAND page size
  (often 4 KiB or larger) exceeds the 512-byte LBA, which is why `mdr remap`
  pads one neighbour block on each side by default.

## Apple diskutil plist keys used

`DeviceIdentifier, DeviceNode, MediaName, TotalSize, Size, DeviceBlockSize,
Internal, RemovableMedia, BusProtocol, SolidState, SMARTStatus, WholeDisk,
ParentWholeDisk, Content, FilesystemType, VolumeName, MountPoint, WritableMedia,
APFSContainerReference, APFSPhysicalStores`. Verify on your macOS version with
`diskutil info -plist diskN`; Apple does not document the plist schema and
Eclectic Light notes SMART sub-keys "may vary, not guaranteed".
