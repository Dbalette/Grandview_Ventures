import errno
import os
import stat
import tempfile
import unittest
from unittest import mock

from driverescue import transfer
from driverescue.transfer import (
    LocalBackend, SshTarBackend, TransferError, TransferStats, build_plan, list_local,
    parse_destination, remote_path,
)
from driverescue.verify import compare

FILES = {
    "Users/me/Documents/a.txt": b"alpha",
    "Users/me/Documents/sub/b.txt": b"beta",
    "Users/me/Pictures/p.jpg": os.urandom(5000),
    "Users/me/Downloads/setup.dmg": os.urandom(3000),
    "Users/me/Library/Caches/junk.bin": b"x" * 100,
    "Users/me/other/z.txt": b"zed",
    ".Spotlight-V100/index": b"idx",
    "System/os.bin": b"os",
}


def make_tree(root):
    for rel, data in FILES.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
    os.symlink("a.txt", os.path.join(root, "Users/me/Documents/link"))


def rels(plan, kind="file"):
    return [e.rel for e in plan.entries if e.kind == kind]


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


def fake_ssh(directory, body):
    path = os.path.join(directory, "fakessh")
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


RUN_LOCALLY = 'shift\nexec sh -c "$1"\n'  # pretend the "remote" computer is this one


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        make_tree(self.tmp.name)

    def test_junk_is_skipped_and_priority_folders_come_first(self):
        plan = build_plan(self.tmp.name)
        files = rels(plan)
        self.assertNotIn(".Spotlight-V100/index", files)
        self.assertIn("Users/me/Downloads/setup.dmg", files)
        first = {name: files.index(name) for name in (
            "Users/me/Documents/a.txt", "Users/me/Pictures/p.jpg", "Users/me/Downloads/setup.dmg")}
        self.assertLess(first["Users/me/Documents/a.txt"], first["Users/me/Pictures/p.jpg"])
        self.assertLess(first["Users/me/Pictures/p.jpg"], first["Users/me/Downloads/setup.dmg"])
        self.assertEqual(plan.total_bytes, sum(len(v) for k, v in FILES.items() if not k.startswith(".Spot")))

    def test_skip_replaceable_drops_installers_and_caches(self):
        files = rels(build_plan(self.tmp.name, skip_replaceable=True))
        self.assertNotIn("Users/me/Downloads/setup.dmg", files)
        self.assertNotIn("Users/me/Library/Caches/junk.bin", files)
        self.assertIn("Users/me/Documents/a.txt", files)

    def test_skip_os_only_applies_at_the_top_level(self):
        files = rels(build_plan(self.tmp.name, skip_os=True))
        self.assertNotIn("System/os.bin", files)
        self.assertIn("Users/me/Library/Caches/junk.bin", files)  # a user's Library is not the OS

    def test_custom_priority_and_exclude(self):
        plan = build_plan(self.tmp.name, priority=["Users/*/other"], excludes=["*/Pictures"])
        files = rels(plan)
        self.assertEqual(files[0], "Users/me/other/z.txt")
        self.assertNotIn("Users/me/Pictures/p.jpg", files)

    def test_unlistable_folder_is_reported_not_fatal(self):
        os.makedirs(os.path.join(self.tmp.name, "Users/me/locked"))

        def picky_scandir(path):
            if str(path).endswith("locked"):
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_scandir(path)

        with mock.patch.object(transfer.os, "scandir", picky_scandir):
            plan = build_plan(self.tmp.name)
        self.assertTrue(any("locked" in e for e in plan.errors))
        self.assertIn("Users/me/Documents/a.txt", rels(plan))


real_scandir = os.scandir


class LocalBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        self.dst = os.path.join(self.tmp.name, "dst")
        os.makedirs(self.src)
        make_tree(self.src)

    def copy(self):
        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = LocalBackend(self.dst)
        backend.prepare()
        backend.run(plan.entries, stats, lambda: None)
        return plan, stats

    def test_copy_then_rerun_resumes_without_recopying(self):
        plan, stats = self.copy()
        for rel, data in FILES.items():
            if not rel.startswith(".Spot"):
                self.assertEqual(read(os.path.join(self.dst, *rel.split("/"))), data, rel)
        self.assertEqual(stats.bytes_done, plan.total_bytes)
        self.assertEqual(os.readlink(os.path.join(self.dst, "Users/me/Documents/link")), "a.txt")
        src_mtime = os.path.getmtime(os.path.join(self.src, "Users/me/Documents/a.txt"))
        self.assertAlmostEqual(os.path.getmtime(os.path.join(self.dst, "Users/me/Documents/a.txt")), src_mtime, 1)
        self.assertEqual(stats.errors, [])
        _, again = self.copy()
        self.assertEqual(again.files_skipped, len(plan.files))
        self.assertEqual(again.bytes_done, plan.total_bytes)

    def test_unreadable_file_is_logged_and_the_rest_still_copies(self):
        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = LocalBackend(self.dst)
        backend.prepare()
        real_open = os.open

        def picky_open(path, *args, **kwargs):
            if str(path).endswith("b.txt"):
                raise PermissionError(errno.EIO, "Input/output error")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(transfer.os, "open", picky_open):
            backend.run(plan.entries, stats, lambda: None)
        self.assertEqual([rel for rel, _ in stats.errors], ["Users/me/Documents/sub/b.txt"])
        self.assertTrue(os.path.exists(os.path.join(self.dst, "Users/me/Documents/a.txt")))
        report = compare(plan.entries, list_local(self.dst))
        self.assertEqual(report.missing, ["Users/me/Documents/sub/b.txt"])
        self.assertFalse(report.ok)

    def test_bad_sector_inside_a_file_is_zero_filled_and_recorded(self):
        big = os.path.join(self.src, "big.bin")
        data = os.urandom(3 * transfer.BLOCK)
        with open(big, "wb") as handle:
            handle.write(data)
        bad_start = transfer.BLOCK + 8 * 4096
        real_pread = transfer.pread_full

        def flaky(fd, length, offset):
            if os.fstat(fd).st_size == len(data) and offset < bad_start + 4096 and offset + length > bad_start:
                raise OSError(errno.EIO, "Input/output error")
            return real_pread(fd, length, offset)

        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = LocalBackend(self.dst)
        backend.prepare()
        with mock.patch.object(transfer, "pread_full", flaky):
            backend.run(plan.entries, stats, lambda: None)
        expected = bytearray(data)
        expected[bad_start:bad_start + 4096] = bytes(4096)
        self.assertEqual(read(os.path.join(self.dst, "big.bin")), bytes(expected))
        self.assertEqual(stats.damaged["big.bin"], [[bad_start, 4096]])
        self.assertEqual(stats.errors, [])


class SshBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        self.dst = os.path.join(self.tmp.name, "remote dir", "Users")  # a space, to test quoting
        os.makedirs(self.src)
        make_tree(self.src)

    def send(self, ssh_body=RUN_LOCALLY):
        ssh = fake_ssh(self.tmp.name, ssh_body)
        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = SshTarBackend("daniel@host", self.dst, [ssh])
        backend.prepare()
        backend.run(plan.entries, stats, lambda: None)
        return plan, stats, backend

    def test_files_arrive_intact_and_a_rerun_skips_them(self):
        plan, stats, backend = self.send()
        for rel, data in FILES.items():
            if not rel.startswith(".Spot"):
                self.assertEqual(read(os.path.join(self.dst, *rel.split("/"))), data, rel)
        self.assertEqual(os.readlink(os.path.join(self.dst, "Users/me/Documents/link")), "a.txt")
        self.assertEqual(stats.bytes_done, plan.total_bytes)
        self.assertEqual(len(backend.existing()), len(plan.files))
        _, again, _ = self.send()
        self.assertEqual(again.files_skipped, len(plan.files))

    def test_bad_sector_is_zero_filled_without_breaking_the_stream(self):
        big = os.path.join(self.src, "big.bin")
        data = os.urandom(2 * transfer.BLOCK)
        with open(big, "wb") as handle:
            handle.write(data)
        bad_start = 16 * 4096
        real_pread = transfer.pread_full

        def flaky(fd, length, offset):
            if os.fstat(fd).st_size == len(data) and offset < bad_start + 4096 and offset + length > bad_start:
                raise OSError(errno.EIO, "Input/output error")
            return real_pread(fd, length, offset)

        with mock.patch.object(transfer, "pread_full", flaky):
            _, stats, _ = self.send()
        expected = bytearray(data)
        expected[bad_start:bad_start + 4096] = bytes(4096)
        self.assertEqual(read(os.path.join(self.dst, "big.bin")), bytes(expected))
        self.assertEqual(stats.damaged["big.bin"], [[bad_start, 4096]])
        self.assertEqual(read(os.path.join(self.dst, "Users/me/Documents/a.txt")), b"alpha")  # stream survived

    def test_unreachable_host_gives_a_clear_error(self):
        ssh = fake_ssh(self.tmp.name, 'echo "ssh: connect to host: No route to host" >&2\nexit 255\n')
        with self.assertRaises(TransferError) as ctx:
            SshTarBackend("daniel@host", self.dst, [ssh]).prepare()
        self.assertIn("No route to host", str(ctx.exception))

    def test_remote_tar_failure_is_reported(self):
        body = 'shift\ncase "$1" in *"tar -x"*) cat >/dev/null; echo "tar: disk full" >&2; exit 2;; esac\nexec sh -c "$1"\n'
        ssh = fake_ssh(self.tmp.name, body)
        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = SshTarBackend("daniel@host", self.dst, [ssh])
        backend.prepare()
        with self.assertRaises(TransferError) as ctx:
            backend.run(plan.entries, stats, lambda: None)
        self.assertIn("disk full", str(ctx.exception))

    def test_connection_dropping_mid_transfer_says_to_rerun(self):
        body = 'shift\ncase "$1" in *"tar -x"*) exit 255;; esac\nexec sh -c "$1"\n'
        ssh = fake_ssh(self.tmp.name, body)
        with open(os.path.join(self.src, "huge.bin"), "wb") as handle:
            handle.write(os.urandom(4 * transfer.BLOCK))
        plan = build_plan(self.src)
        stats = TransferStats(plan.total_bytes, len(plan.files))
        backend = SshTarBackend("daniel@host", self.dst, [ssh])
        backend.prepare()
        with self.assertRaises(TransferError) as ctx:
            backend.run(plan.entries, stats, lambda: None)
        self.assertTrue("again" in str(ctx.exception) or "tar failed" in str(ctx.exception))


class DestinationTests(unittest.TestCase):
    def test_parse_destination(self):
        self.assertEqual(parse_destination("daniel@192.168.12.180:el-capitan-rescue/Users/"),
                         ("ssh", "daniel@192.168.12.180", "el-capitan-rescue/Users/"))
        self.assertEqual(parse_destination("/Volumes/Backup/x"), ("local", "", "/Volumes/Backup/x"))
        self.assertEqual(parse_destination("./a:b")[0], "local")
        self.assertEqual(parse_destination("C:\\data")[0], "local")

    def test_remote_path_quoting(self):
        self.assertEqual(remote_path("plain"), "plain")
        self.assertEqual(remote_path("a b"), "'a b'")
        self.assertEqual(remote_path("~/x y"), "\"$HOME\"/'x y'")
        self.assertEqual(remote_path("~"), '"$HOME"')


if __name__ == "__main__":
    unittest.main()
