import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


path = Path(__file__).resolve().parents[1] / 'ports/rpd-cpu-topology-m10/commit.py'
spec = importlib.util.spec_from_file_location('boot_commit', path)
commit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(commit)


class BootCommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pending = self.root / 'run/rpd-m10-boot.pending'
        self.pending.parent.mkdir()
        self.deviceinfo = self.root / 'usr/share/deviceinfo/deviceinfo'
        self.deviceinfo.parent.mkdir(parents=True)
        self.deviceinfo.touch()
        self.calls = []

    def recompose(self, argv, check):
        self.calls.append((argv, check))
        self.pending.touch()

    def finish(self, stage, find=lambda name: '/sbin/mkinitfs'):
        commit.finish(stage, self.root, self.recompose, find)

    def test_transaction_rebuilds_only_after_database_commit(self):
        self.finish('pre-commit')
        self.pending.touch()  # mkinitfs trigger runs before APK saves its DB.
        self.finish('pre-commit')
        self.assertEqual(self.calls, [])
        self.finish('post-commit')
        self.assertEqual(self.calls, [(['/sbin/mkinitfs'], True)])
        self.assertFalse(self.pending.exists())
        self.finish('post-commit')
        self.assertEqual(len(self.calls), 1)

    def test_failure_preserves_retry_request(self):
        self.pending.touch()
        def fail(argv, check):
            raise subprocess.CalledProcessError(1, argv)
        with self.assertRaises(subprocess.CalledProcessError):
            commit.finish('post-commit', self.root, fail, lambda name: '/sbin/mkinitfs')
        self.assertTrue(self.pending.exists())

    def test_plain_alpine_and_missing_mkinitfs_do_not_rebuild(self):
        self.pending.touch()
        self.finish('post-commit', find=lambda name: None)
        self.deviceinfo.unlink()
        self.finish('post-commit')
        self.assertEqual(self.calls, [])
        self.assertTrue(self.pending.exists())
