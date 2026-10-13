import json
import unittest
from unittest import mock

from driverescue import health
from driverescue.devices import Drive, Volume
from driverescue.health import Level, assess, parse_diskutil_smart, parse_fsck_output, parse_smart_json

# Verbatim from the real session: the first attempt, on the mounted volume.
LIVE_MODE_FAILURE = """\
Started file system verification on disk20s1 (EL Capitan)
Verifying file system
Volume could not be unmounted
Using live mode
Performing fsck_apfs -n -l -x /dev/rdisk20s1
error: could not freeze volume: Illegal byte sequence
File system check exit code is 71
Restoring the original state found as mounted
Error: -69845: File system verify or repair failed
Underlying error: 71
The operation might have failed in part because an unmount operation was dissented by PID 0 (kernel_task)
"""

# Verbatim from the real session: the check on the unmounted volume.
OFFLINE_CORRUPT = """\
Started file system verification on disk20s1 (EL Capitan)
Verifying file system
Volume is already unmounted
Performing fsck_apfs -n -x /dev/rdisk20s1
Checking the container superblock
Checking the checkpoint with transaction ID 123484
Checking the fsroot tree
error: (oid 0x2f5f) apfs_root: btn: dev_read_finish(183568, 1): Input/output error
warning: (oid 0x2f5f) apfs_root: btn: invalid o_cksum (0x404620000)
fsroot tree is invalid
The volume /dev/rdisk20s1 with UUID 5F991973-D5BE-346D-BCBF-57E5D263897B was found to be corrupt and cannot be repaired
Verifying allocated space
The volume /dev/rdisk20s1 with UUID 5F991973-D5BE-346D-BCBF-57E5D263897B could not be verified completely
File system check exit code is 8
Restoring the original state found as unmounted
Error: -69845: File system verify or repair failed
Underlying error: 8
"""

HEALTHY = """\
Started file system verification on disk3s1 (Macintosh HD)
Checking volume
The volume /dev/rdisk3s1 appears to be OK
File system check exit code is 0
"""


def codes(findings):
    return {f.code for f in findings}


class FsckParsingTests(unittest.TestCase):
    def test_live_mode_failure_is_inconclusive_not_corruption(self):
        findings = parse_fsck_output(LIVE_MODE_FAILURE)
        self.assertEqual(codes(findings), {"LIVE_CHECK_UNAVAILABLE", "UNMOUNT_BLOCKED"})
        verdict = assess(findings)
        self.assertEqual(verdict.level, Level.WATCH)
        self.assertIn("lsof", verdict.advice[0])  # tells you how to find what holds the drive open

    def test_real_corruption_output_says_rescue_first(self):
        findings = parse_fsck_output(OFFLINE_CORRUPT)
        self.assertTrue({"IO_ERROR", "CHECKSUM_INVALID", "FS_CORRUPT", "VERIFY_INCOMPLETE"} <= codes(findings))
        verdict = assess(findings)
        self.assertEqual(verdict.level, Level.RESCUE_NOW)
        self.assertTrue(any("Do NOT run First Aid" in line for line in verdict.advice))
        io_error = next(f for f in findings if f.code == "IO_ERROR")
        self.assertIn("dev_read_finish(183568, 1)", io_error.detail)

    def test_io_error_without_smart_suggests_trying_another_cable(self):
        verdict = assess(parse_fsck_output(OFFLINE_CORRUPT))
        self.assertTrue(any("another cable" in line for line in verdict.advice))

    def test_healthy_volume(self):
        verdict = assess(parse_fsck_output(HEALTHY))
        self.assertEqual(verdict.level, Level.OK)
        self.assertEqual(verdict.headline, "No problems found.")


def ata(**values):
    ids = {"reallocated": 5, "reported_uncorrect": 187, "pending": 197,
           "offline_uncorrectable": 198, "crc_errors": 199}
    return {
        "smart_status": {"passed": True},
        "ata_smart_attributes": {"table": [
            {"id": ids[name], "name": name, "raw": {"value": value}} for name, value in values.items()
        ]},
    }


class SmartTests(unittest.TestCase):
    def test_clean_drive(self):
        findings = parse_smart_json(ata(reallocated=0, pending=0, crc_errors=0))
        self.assertEqual(codes(findings), {"SMART_OK"})

    def test_failed_overall_status(self):
        data = ata()
        data["smart_status"]["passed"] = False
        self.assertEqual(assess(parse_smart_json(data)).level, Level.FAILING)

    def test_pending_sectors_mean_rescue_now(self):
        verdict = assess(parse_smart_json(ata(pending=3)))
        self.assertEqual(verdict.level, Level.RESCUE_NOW)

    def test_few_reallocated_sectors_are_a_watch_item_many_are_not(self):
        self.assertEqual(assess(parse_smart_json(ata(reallocated=4))).level, Level.WATCH)
        self.assertEqual(assess(parse_smart_json(ata(reallocated=80))).level, Level.RESCUE_NOW)

    def test_crc_errors_blame_the_cable(self):
        verdict = assess(parse_smart_json(ata(crc_errors=12)))
        self.assertEqual(verdict.level, Level.WATCH)
        self.assertTrue(any("cable" in line for line in verdict.advice))

    def test_nvme_media_errors_and_wear(self):
        data = {"smart_status": {"passed": True},
                "nvme_smart_health_information_log": {"critical_warning": 0, "media_errors": 2, "percentage_used": 95}}
        found = codes(parse_smart_json(data))
        self.assertEqual(found, {"SMART_MEDIA_ERRORS", "SMART_WORN_OUT"})

    def test_unreadable_smart_is_reported_not_guessed(self):
        findings = parse_smart_json({})
        self.assertEqual(codes(findings), {"SMART_UNAVAILABLE"})
        self.assertEqual(assess(findings).level, Level.OK)
        self.assertTrue(any("smartmontools" in line for line in assess(findings).advice))

    def test_diskutil_smart_status(self):
        self.assertEqual(codes(parse_diskutil_smart("Verified")), {"SMART_OK"})
        self.assertEqual(codes(parse_diskutil_smart("Failing")), {"SMART_FAILED"})
        self.assertEqual(parse_diskutil_smart("Not Supported"), [])


class GatheringTests(unittest.TestCase):
    def test_read_smart_retries_with_sat_passthrough(self):
        calls = []

        def runner(cmd):
            calls.append(cmd)
            if "sat" in cmd:
                return 0, json.dumps(ata(pending=0)), ""
            return 0, json.dumps({"json_format_version": [1, 0]}), ""

        with mock.patch.object(health.shutil, "which", return_value="/usr/bin/smartctl"):
            findings = health.read_smart("/dev/disk5", runner)
        self.assertEqual(codes(findings), {"SMART_OK"})
        self.assertEqual(len(calls), 2)

    def test_read_smart_without_smartctl(self):
        with mock.patch.object(health.shutil, "which", return_value=None):
            self.assertEqual(codes(health.read_smart("/dev/disk5")), {"SMART_UNAVAILABLE"})

    def test_collect_findings_runs_verify_on_each_macos_volume(self):
        drive = Drive("disk5", "/dev/disk5", volumes=[Volume("disk20s1", "EL Capitan")], smart_status="Not Supported")

        def runner(cmd):
            if cmd[:2] == ["diskutil", "verifyVolume"]:
                return 1, OFFLINE_CORRUPT, ""
            return 127, "", "not found"

        with mock.patch.object(health.shutil, "which", return_value=None):
            findings = health.collect_findings(drive, None, "macos", runner)
        self.assertEqual(assess(findings).level, Level.RESCUE_NOW)


if __name__ == "__main__":
    unittest.main()
