import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "tests", "fixtures")

from mdr import diskutil, rescue, smart  # noqa: E402


def fixture(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


class DiskutilParsing(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(diskutil.normalize_identifier("/dev/rdisk4"), "disk4")
        self.assertEqual(diskutil.normalize_identifier("disk4s2"), "disk4s2")
        with self.assertRaises(ValueError):
            diskutil.normalize_identifier("sda")

    def test_whole_disk_info(self):
        di = diskutil.parse_info_plist(fixture("diskutil_info_disk4.plist"))
        self.assertEqual(di.identifier, "disk4")
        self.assertEqual(di.raw_node, "/dev/rdisk4")
        self.assertTrue(di.whole)
        self.assertTrue(di.is_external)
        self.assertTrue(di.solid_state)
        self.assertEqual(di.size, 500107862016)
        self.assertEqual(di.block_size, 512)
        self.assertEqual(di.protocol, "USB")
        self.assertEqual(di.smart_status, "Not Supported")

    def test_volume_info(self):
        di = diskutil.parse_info_plist(fixture("diskutil_info_disk4s2.plist"))
        self.assertFalse(di.whole)
        self.assertEqual(di.parent_whole, "disk4")
        self.assertEqual(di.filesystem, "hfs")
        self.assertEqual(di.mount_point, "/Volumes/OldSSD")

    def test_list_children(self):
        entries = diskutil.parse_list_plist(fixture("diskutil_list_external.plist"))
        self.assertEqual([e["DeviceIdentifier"] for e in entries], ["disk4"])
        self.assertEqual(diskutil.child_identifiers(entries[0]), ["disk4s1", "disk4s2"])

    def test_attach_output(self):
        text = "/dev/disk7          \tGUID_partition_scheme          \t\n/dev/disk7s1        \tEFI                            \t\n/dev/disk7s2        \tApple_HFS                      \t\n"
        self.assertEqual(diskutil.parse_attach_output(text), ["disk7", "disk7s1", "disk7s2"])


class SmartParsing(unittest.TestCase):
    def test_failing_sata_ssd(self):
        s = smart.parse(json.loads(fixture("smartctl_sata_ssd_failing.json")))
        self.assertTrue(s.available)
        self.assertEqual(s.model, "Samsung SSD 850 EVO 500GB")
        self.assertEqual(s.reallocated, 14)
        self.assertEqual(s.pending, 6)
        self.assertEqual(s.offline_uncorrectable, 6)
        self.assertEqual(s.reported_uncorrectable, 27)
        self.assertEqual(s.erase_fail, 3)
        self.assertEqual(s.wear_pct_used, 78)  # 100 - normalized 22
        self.assertEqual(s.power_on_hours, 41230)
        sev = {f["severity"] for f in smart.findings(s)}
        self.assertIn("critical", sev)

    def test_nvme_ok(self):
        s = smart.parse(json.loads(fixture("smartctl_nvme_ok.json")))
        self.assertTrue(s.available)
        self.assertEqual(s.nvme_percentage_used, 1)
        self.assertEqual(s.nvme_media_errors, 0)
        self.assertEqual(s.wear_pct_used, 1)
        self.assertTrue(s.overall_passed)
        sev = {f["severity"] for f in smart.findings(s)}
        self.assertNotIn("critical", sev)

    def test_usb_unsupported(self):
        s = smart.parse(json.loads(fixture("smartctl_usb_unsupported.json")))
        self.assertFalse(s.available)
        self.assertIn("Unable to detect device type", s.reason)


class MapfileParsing(unittest.TestCase):
    def test_parse(self):
        st = rescue.parse_mapfile(fixture("ddrescue.map").decode())
        self.assertEqual(st.current_pos, 0x7470C00000)
        self.assertEqual(st.current_status, "+")
        self.assertEqual(st.bad, 0x400 + 0x1000)
        self.assertEqual(len(st.bad_ranges), 2)
        self.assertTrue(st.finished)
        self.assertGreater(st.pct_rescued(), 99.99)

    def test_badmap_from_mapfile(self):
        total = 0x12A05F200 + 0x400 + 0x3B9ACA000 + 0x1000 + 0x6F8E6D5A00
        bm = rescue.badmap_from_mapfile(fixture("ddrescue.map").decode(), "/dev/rdisk4", 512, total)
        self.assertEqual(bm.bad_blocks, (0x400 + 0x1000) // 512)
        self.assertTrue(bm.complete)

    def test_pass_commands(self):
        cmds = rescue.pass_commands("/dev/rdisk4", "/v/b/d.img", "/v/b/d.map", 4096, [1, 2, 3], "ddrescue")
        self.assertEqual(cmds[0], ["ddrescue", "-b", "4096", "-n", "/dev/rdisk4", "/v/b/d.img", "/v/b/d.map"])
        self.assertIn("-r3", cmds[1])
        self.assertIn("-R", cmds[2])
        with self.assertRaises(ValueError):
            rescue.pass_commands("a", "b", "c", 512, [9])


if __name__ == "__main__":
    unittest.main()
