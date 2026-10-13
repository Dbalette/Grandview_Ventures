import json
import plistlib
import unittest

from driverescue.devices import linux_drives, macos_drives, resolve_target


def plist(obj):
    return plistlib.dumps(obj).decode()


def mac_runner(cmd):
    """Answers diskutil the way a Mac with the SABRENT drive from the real session would."""
    key = tuple(cmd[1:])
    if key == ("list", "-plist", "external", "physical"):
        return 0, plist({"AllDisksAndPartitions": [
            {"DeviceIdentifier": "disk4", "Size": 16100000000, "Partitions": [
                {"DeviceIdentifier": "disk4s1", "Content": "EFI", "VolumeName": "EFI"},
                {"DeviceIdentifier": "disk4s2", "Content": "Microsoft Basic Data",
                 "VolumeName": "UBUNTU", "MountPoint": "/Volumes/UBUNTU", "Size": 15900000000}]},
            {"DeviceIdentifier": "disk5", "Size": 480103981056, "Partitions": [
                {"DeviceIdentifier": "disk5s1", "Content": "EFI", "VolumeName": "EFI"},
                {"DeviceIdentifier": "disk5s2", "Content": "Apple_APFS", "Size": 479900000000}]},
        ]}), ""
    if key == ("info", "-plist", "disk5"):
        return 0, plist({"DeviceNode": "/dev/disk5", "MediaName": "SABRENT Media", "BusProtocol": "USB",
                         "Internal": False, "SMARTStatus": "Not Supported"}), ""
    if key == ("info", "-plist", "disk4"):
        return 0, plist({"DeviceNode": "/dev/disk4", "MediaName": "USB Flash", "BusProtocol": "USB",
                         "Internal": False}), ""
    if key == ("info", "-plist", "disk5s2"):
        return 0, plist({"APFSContainerReference": "disk20"}), ""
    if key == ("list", "-plist", "disk20"):
        return 0, plist({"AllDisksAndPartitions": [{"DeviceIdentifier": "disk20", "APFSVolumes": [
            {"DeviceIdentifier": "disk20s1", "VolumeName": "EL Capitan",
             "MountPoint": "/Volumes/EL Capitan", "Size": 447000000000}]}]}), ""
    return 1, "", "unexpected: " + " ".join(cmd)


LSBLK = {"blockdevices": [
    {"name": "sda", "path": "/dev/sda", "size": 1920383410176, "model": "Internal SSD", "tran": "sata",
     "rm": False, "type": "disk", "children": [
         {"name": "sda2", "path": "/dev/sda2", "size": 1900000000000, "type": "part", "fstype": "ext4",
          "label": None, "mountpoint": "/", "mountpoints": ["/"]}]},
    {"name": "sdb", "path": "/dev/sdb", "size": 480103981056, "model": "SanDisk SSD ", "tran": "usb",
     "rm": False, "type": "disk", "children": [
         {"name": "sdb1", "path": "/dev/sdb1", "size": 480000000000, "type": "part", "fstype": "ext4",
          "label": "OLD", "mountpoint": None, "mountpoints": [None]}]},
    {"name": "loop0", "path": "/dev/loop0", "size": 100, "type": "loop"},
]}


class MacDriveTests(unittest.TestCase):
    def test_lists_external_drives_with_apfs_volumes(self):
        drives = macos_drives(mac_runner)
        self.assertEqual([d.identifier for d in drives], ["disk4", "disk5"])
        sabrent = drives[1]
        self.assertEqual(sabrent.model, "SABRENT Media")
        self.assertEqual(sabrent.size, 480103981056)
        self.assertEqual(sabrent.raw_node, "/dev/rdisk5")
        self.assertEqual(sabrent.mount_points, ["/Volumes/EL Capitan"])
        self.assertEqual(sabrent.volumes[0].identifier, "disk20s1")
        self.assertEqual(drives[0].volumes[0].name, "UBUNTU")  # EFI partition is not listed

    def test_resolve_target_accepts_ids_raw_paths_volumes_and_mounts(self):
        drives = macos_drives(mac_runner)
        for text in ("disk5", "/dev/disk5", "/dev/rdisk5", "disk5s2"):
            drive, volume = resolve_target(text, drives)
            self.assertEqual(drive.identifier, "disk5", text)
        drive, volume = resolve_target("disk20s1", drives)
        self.assertEqual((drive.identifier, volume.name), ("disk5", "EL Capitan"))
        drive, volume = resolve_target("/Volumes/EL Capitan", drives)
        self.assertEqual(drive.identifier, "disk5")
        self.assertIsNone(resolve_target("disk99", drives))

    def test_diskutil_failure_gives_empty_list(self):
        self.assertEqual(macos_drives(lambda cmd: (1, "", "boom")), [])


class LinuxDriveTests(unittest.TestCase):
    def runner(self, with_mountpoints_column=True):
        def run(cmd):
            if "MOUNTPOINTS" in cmd[-1] and not with_mountpoints_column:
                return 1, "", "unknown column"
            return 0, json.dumps(LSBLK), ""
        return run

    def test_external_only_by_default(self):
        drives = linux_drives(self.runner())
        self.assertEqual([d.identifier for d in drives], ["sdb"])
        self.assertEqual(drives[0].model, "SanDisk SSD")
        self.assertEqual(drives[0].bus, "USB")
        self.assertEqual(drives[0].volumes[0].fs, "ext4")
        self.assertEqual(drives[0].mount_points, [])

    def test_include_internal_and_skip_loop_devices(self):
        drives = linux_drives(self.runner(), include_internal=True)
        self.assertEqual([d.identifier for d in drives], ["sda", "sdb"])
        self.assertEqual(drives[0].mount_points, ["/"])

    def test_falls_back_when_lsblk_is_old(self):
        drives = linux_drives(self.runner(with_mountpoints_column=False))
        self.assertEqual([d.identifier for d in drives], ["sdb"])

    def test_resolve_partition_to_drive(self):
        drives = linux_drives(self.runner())
        drive, volume = resolve_target("/dev/sdb1", drives)
        self.assertEqual((drive.identifier, volume.name), ("sdb", "OLD"))


if __name__ == "__main__":
    unittest.main()
