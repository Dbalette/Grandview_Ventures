import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from driverescue import cli
from driverescue.devices import Drive, Volume

from .test_transfer import FILES, make_tree

MIB = 1024 * 1024


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = os.path.join(self.tmp.name, "work")
        self.src = os.path.join(self.tmp.name, "src")
        self.dst = os.path.join(self.tmp.name, "dst")
        os.makedirs(self.src)
        make_tree(self.src)

    def test_refresh_plan_prints_but_runs_nothing(self):
        code, out = run_cli("refresh-plan", "--drive", "disk5", "--workdir", self.work)
        self.assertEqual(code, 0)
        self.assertIn("disk5", out)
        self.assertIn("DESTROYS", out)
        self.assertIn("STOP unless your files are safe", out)

    def test_drives_lists_what_it_finds(self):
        drive = Drive("disk5", "/dev/disk5", model="SABRENT Media", size=480103981056, bus="USB",
                      volumes=[Volume("disk20s1", "EL Capitan", "/Volumes/EL Capitan")])
        with mock.patch.object(cli, "list_drives", return_value=[drive]):
            code, out = run_cli("drives", "--workdir", self.work)
        self.assertEqual(code, 0)
        self.assertIn("SABRENT Media", out)
        self.assertIn("480.1 GB", out)
        self.assertIn("EL Capitan [/Volumes/EL Capitan]", out)

    def test_dry_run_reports_size_and_copies_nothing(self):
        code, out = run_cli("rescue", self.src, self.dst, "--dry-run", "--workdir", self.work)
        self.assertEqual(code, 0)
        self.assertIn("Plan for", out)
        self.assertIn("Biggest top-level folders", out)
        self.assertFalse(os.path.exists(self.dst))

    def test_rescue_then_verify_then_detect_a_missing_file(self):
        code, out = run_cli("rescue", self.src, self.dst, "--workdir", self.work)
        self.assertEqual(code, 0, out)
        self.assertIn("Done in", out)
        code, out = run_cli("verify", self.src, self.dst, "--workdir", self.work)
        self.assertEqual(code, 0, out)
        self.assertIn("copy matches the source", out)

        os.unlink(os.path.join(self.dst, "Users/me/Pictures/p.jpg"))
        code, out = run_cli("verify", self.src, self.dst, "--workdir", self.work)
        self.assertEqual(code, 2)
        self.assertIn("Users/me/Pictures/p.jpg", out)
        self.assertIn("INCOMPLETE", out)

        code, out = run_cli("rescue", self.src, self.dst, "--workdir", self.work)  # resume
        self.assertEqual(code, 0, out)
        self.assertEqual(run_cli("verify", self.src, self.dst, "--workdir", self.work)[0], 0)

    def test_rescue_refuses_when_the_destination_is_too_small(self):
        with mock.patch.object(cli, "enough_space", return_value=(False, 10)):
            code, out = run_cli("rescue", self.src, self.dst, "--workdir", self.work)
        self.assertEqual(code, 2)
        self.assertIn("Not enough free space", out)

    def test_status_before_and_after_a_job(self):
        code, out = run_cli("status", "--workdir", self.work)
        self.assertIn("No jobs have run yet", out)
        run_cli("rescue", self.src, self.dst, "--workdir", self.work)
        code, out = run_cli("status", "--workdir", self.work)
        self.assertIn("rescue", out)
        self.assertIn("[finished]", out)

    def test_scan_and_image_of_a_file_standing_in_for_a_drive(self):
        disk = os.path.join(self.tmp.name, "old-drive.bin")
        data = os.urandom(4 * MIB)
        with open(disk, "wb") as handle:
            handle.write(data)

        code, out = run_cli("scan", disk, "--chunk-mb", "1", "--workdir", self.work)
        self.assertEqual(code, 0, out)
        self.assertIn("Unreadable: 0 region(s)", out)

        image = os.path.join(self.tmp.name, "copy.img")
        code, out = run_cli("image", disk, image, "--chunk-mb", "1", "--workdir", self.work)
        self.assertEqual(code, 0, out)
        with open(image, "rb") as handle:
            self.assertEqual(handle.read(), data)

        code, out = run_cli("image", disk, image, "--workdir", self.work)  # map exists: resume, still fine
        self.assertEqual(code, 0, out)
        self.assertIn("Resuming", out)

        os.unlink(image + ".map.json")
        code, out = run_cli("image", disk, image, "--workdir", self.work)  # image but no map: refuse
        self.assertEqual(code, 2)
        self.assertIn("already exists", out)

    def test_mounted_drive_is_not_read_without_unmounting(self):
        drive = Drive("disk5", "/dev/disk5", size=4 * MIB,
                      volumes=[Volume("disk20s1", "EL Capitan", "/Volumes/EL Capitan")])
        resolved = (drive, None)
        with mock.patch.object(cli, "resolve_target", return_value=resolved), \
                mock.patch.object(cli, "list_drives", return_value=[drive]), \
                mock.patch.object(cli, "detect_system", return_value="macos"):
            code, out = run_cli("scan", "disk5", "--workdir", self.work)
        self.assertEqual(code, 2)
        self.assertIn("diskutil unmountDisk disk5", out)
        self.assertIn("--allow-mounted", out)

    def test_image_refuses_to_write_onto_the_drive_being_rescued(self):
        with tempfile.TemporaryDirectory() as mount:
            drive = Drive("disk5", "/dev/disk5", size=4 * MIB,
                          volumes=[Volume("disk5s1", "Old", mount)])
            with mock.patch.object(cli, "resolve_target", return_value=(drive, None)), \
                    mock.patch.object(cli, "list_drives", return_value=[drive]):
                code, out = run_cli("image", "disk5", os.path.join(mount, "x.img"),
                                    "--allow-mounted", "--workdir", self.work)
        self.assertEqual(code, 2)
        self.assertIn("overwrite", out)

    def test_unknown_drive_lists_what_is_connected(self):
        with mock.patch.object(cli, "list_drives", return_value=[]):
            code, out = run_cli("check", "disk99", "--workdir", self.work)
        self.assertEqual(code, 1)
        self.assertIn("Could not find a drive", out)


if __name__ == "__main__":
    unittest.main()
