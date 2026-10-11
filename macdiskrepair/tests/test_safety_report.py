import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "tests", "fixtures")

from mdr import diskutil, fsrepair, report, safety  # noqa: E402


def info(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return diskutil.parse_info_plist(fh.read())


class Safety(unittest.TestCase):
    def test_external_whole_disk_ok(self):
        di = info("diskutil_info_disk4.plist")
        chk = safety.evaluate(di, boot_disk="disk0", mounted_children=[], require_unmounted=True)
        self.assertTrue(chk.ok, chk.reasons)

    def test_refuses_partition(self):
        di = info("diskutil_info_disk4s2.plist")
        chk = safety.evaluate(di, "disk0", [], require_unmounted=False)
        self.assertFalse(chk.ok)
        self.assertIn("not a whole disk", chk.reasons[0])

    def test_refuses_internal_and_boot(self):
        di = info("diskutil_info_disk4.plist")
        di.internal = True
        chk = safety.evaluate(di, boot_disk="disk4", mounted_children=[], require_unmounted=False)
        self.assertFalse(chk.ok)
        self.assertEqual(len(chk.reasons), 2)

    def test_refuses_mounted_when_writing(self):
        di = info("diskutil_info_disk4.plist")
        chk = safety.evaluate(di, "disk0", ["disk4s2 at /Volumes/OldSSD"], require_unmounted=True)
        self.assertFalse(chk.ok)
        self.assertIn("still mounted", chk.reasons[0])
        chk2 = safety.evaluate(di, "disk0", ["disk4s2 at /Volumes/OldSSD"], require_unmounted=False)
        self.assertTrue(chk2.ok)

    def test_typed_confirmation(self):
        self.assertTrue(safety.confirm_typed("disk4", "x", input_fn=lambda _: "disk4"))
        self.assertFalse(safety.confirm_typed("disk4", "x", input_fn=lambda _: "disk0"))
        self.assertFalse(safety.confirm_typed("disk4", "x", input_fn=lambda _: (_ for _ in ()).throw(EOFError())))


class Grading(unittest.TestCase):
    def test_clean_disk_is_A(self):
        smart = {"available": True, "overall_passed": True, "wear_pct_used": 5}
        badmap = {"bad_blocks": 0, "bad_bytes": 0, "total_bytes": 500107862016, "complete": True, "slow_ranges": []}
        a = report.grade(smart, badmap, {"partition_map_ok": True, "volumes": [{"ok": True}]})
        self.assertEqual(a.grade, "A")

    def test_smart_failed_is_F(self):
        a = report.grade({"available": True, "overall_passed": False}, None, None)
        self.assertEqual(a.grade, "F")

    def test_corrupted_blocks_no_smart(self):
        # The user's situation: USB SSD, no SMART, a handful of bad blocks found by the scan.
        badmap = {"bad_blocks": 40, "bad_bytes": 40 * 512, "total_bytes": 500107862016, "complete": True, "slow_ranges": [[0, 1]]}
        fs = {"partition_map_ok": True, "volumes": [{"ok": False, "identifier": "disk4s2", "filesystem": "hfs", "action": "verify"}]}
        a = report.grade({"available": False}, badmap, fs)
        self.assertIn(a.grade, ("B", "C"))
        self.assertTrue(any("unreadable blocks" in r for r in a.reasons))
        # After a successful remap the grade should not get worse.
        a2 = report.grade({"available": False}, badmap, {"partition_map_ok": True, "volumes": [{"ok": True}]},
                          {"attempted_blocks": 40, "still_bad": 0})
        self.assertGreaterEqual(a2.score, a.score)

    def test_remap_failure_degrades(self):
        badmap = {"bad_blocks": 5000, "bad_bytes": 5000 * 4096, "total_bytes": 500107862016, "complete": True}
        a = report.grade(None, badmap, None, {"attempted_blocks": 5000, "still_bad": 4000})
        self.assertIn(a.grade, ("D", "F"))

    def test_render_markdown(self):
        a = report.grade(None, None, None)
        md = report.render_markdown("T", {"identifier": "disk4", "size": 10}, None, [], None, None, None, None, a)
        self.assertIn("# T", md)
        self.assertIn("Verdict", md)


class ManualCommands(unittest.TestCase):
    def test_manual(self):
        self.assertEqual(fsrepair.manual_command("apfs", False, "/dev/disk4s2"), "sudo fsck_apfs -n -S /dev/disk4s2")
        self.assertEqual(fsrepair.manual_command("hfs", True, "/dev/disk4s2"), "sudo fsck_hfs -fy /dev/disk4s2")
        self.assertEqual(fsrepair.manual_command("exfat", True, "/dev/disk4s2"), "sudo fsck_exfat -y /dev/disk4s2")
        self.assertIn("no native checker", fsrepair.manual_command("ntfs", False, "/dev/disk4s2"))
        self.assertEqual(fsrepair.manual_command("", True, "/dev/x"), "")


if __name__ == "__main__":
    unittest.main()
