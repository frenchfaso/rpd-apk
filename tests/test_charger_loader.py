import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ChargerLoaderTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / 'ports/rpd-backlight-m10/rpd-charger-m10-load'
        loader = importlib.machinery.SourceFileLoader('charger_loader', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.m = importlib.util.module_from_spec(spec)
        loader.exec_module(self.m)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.m.PARAMS = root / 'parameters'
        self.m.SUPPLIES = root / 'supplies'
        self.m.SUPPLIES.mkdir()
        (self.m.SUPPLIES / 'm10-battery').mkdir()
        self.m.COMPATIBLE = root / 'compatible'
        self.m.COMPATIBLE.write_bytes(b'lenovo,tbx505x\0')
        self.calls = []

    def run_cmd(self, *args, **kwargs):
        self.calls.append(args)
        return SimpleNamespace(returncode=0, stdout='')

    def main(self):
        with patch.object(self.m.sys, 'argv', ['loader']), patch.object(self.m, 'run', self.run_cmd):
            self.m.main()

    def test_mismatched_kernel_does_not_load_or_write(self):
        with patch.object(self.m, 'matching', return_value=False):
            self.main()
        self.assertEqual(self.calls, [])

    def test_other_board_does_not_load(self):
        self.m.COMPATIBLE.write_bytes(b'other-board\0')
        self.main()
        self.assertEqual(self.calls, [])

    def test_native_pmic_provider_skips_but_accessory_does_not(self):
        native = self.m.SUPPLIES.parent / '200f000.spmi' / 'native-usb'
        native.mkdir(parents=True)
        link = self.m.SUPPLIES / 'native'
        link.symlink_to(native)
        with patch.object(self.m, 'matching', return_value=True):
            self.main()
        self.assertEqual(self.calls, [])
        link.unlink()
        (self.m.SUPPLIES / 'bluetooth-headset').mkdir()
        self.assertFalse(self.m.native_provider())

    def test_successful_start_and_repeated_start(self):
        self.m.PARAMS.mkdir()
        (self.m.PARAMS / 'status').write_text('applied=1 dirty=1')
        with patch.object(self.m, 'matching', return_value=True):
            self.main()
        self.assertEqual(self.calls, [])

    def test_failed_apply_runs_verified_cleanup(self):
        self.m.PARAMS.mkdir()
        (self.m.PARAMS / 'status').write_text('applied=0 dirty=0')
        with patch.object(self.m, 'matching', return_value=True), patch.object(self.m, 'stop') as stop:
            with self.assertRaises(RuntimeError):
                self.main()
            self.assertEqual(stop.call_count, 2)
        self.assertIn(('modprobe', 'm10_charger'), self.calls)

    def test_stop_never_unloads_dirty_module(self):
        self.m.PARAMS.mkdir()
        (self.m.PARAMS / 'status').write_text('applied=0 dirty=1')
        with patch.object(self.m, 'run', self.run_cmd):
            with self.assertRaisesRegex(RuntimeError, 'rollback pending'):
                self.m.stop()
        self.assertEqual(self.calls, [])

    def test_stop_unloads_after_verified_rollback(self):
        self.m.PARAMS.mkdir()
        (self.m.PARAMS / 'status').write_text('applied=0 dirty=0')
        with patch.object(self.m, 'run', self.run_cmd):
            self.m.stop()
        self.assertEqual(self.calls, [('modprobe', '-r', 'm10_charger')])


if __name__ == '__main__':
    unittest.main()
