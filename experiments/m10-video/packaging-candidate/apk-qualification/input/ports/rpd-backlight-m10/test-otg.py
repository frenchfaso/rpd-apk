"""Exercise fail-closed behavior without accessing real hardware."""
import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch


class ProbeTests(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader(
            'otg_trial', str(pathlib.Path(__file__).with_name('rpd-usb-otg-m10')))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.probe = importlib.util.module_from_spec(spec)
        loader.exec_module(self.probe)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name in ('ROLE', 'ID', 'STOP', 'VOLTAGE'):
            setattr(self.probe, name, pathlib.Path(self.temp.name) / name)
        self.probe.ADC = pathlib.Path(self.temp.name) / 'adc'
        (self.probe.ADC / 'iio:device8').mkdir(parents=True)
        self.probe.VOLTAGE = self.probe.ADC / 'iio:device8/in_voltage_usb_in_v_div_16_input'
        self.probe.ROLE.write_text('gadget\n')
        self.probe.ID.write_text('0\n')
        self.probe.VOLTAGE.write_text('7000\n')
        self.commands = []

    def command(self, *args):
        self.commands.append(args)
        if args[:2] == ('modprobe', 'm10_otg_vbus'):
            self.probe.STOP.write_text('0\n')
        elif args[0] == 'rmmod':
            self.assertEqual(self.probe.STOP.read_text(), '1\n')
            self.probe.STOP.unlink()

    def exercise(self, step):
        with patch.object(self.probe, 'command', self.command), \
             patch.object(self.probe, 'log'), \
             patch.object(self.probe, 'kernel_matches', return_value=True), \
             patch.object(self.probe.time, 'sleep', side_effect=step):
            with self.assertRaises(StopIteration):
                self.probe.run()

    def test_unplug_cuts_power_and_returns_gadget(self):
        count = 0
        def step(_):
            nonlocal count
            count += 1
            if count == 3:
                self.assertTrue(self.probe.STOP.exists())
                self.assertEqual(self.probe.ROLE.read_text(), 'host\n')
                self.probe.ID.write_text('1\n')
            elif count == 4:
                self.assertFalse(self.probe.STOP.exists())
                self.assertEqual(self.probe.ROLE.read_text(), 'gadget\n')
                raise StopIteration
        self.exercise(step)

    def test_external_power_never_enables_vbus(self):
        self.probe.VOLTAGE.write_text('5000000\n')
        count = 0
        def step(_):
            nonlocal count
            count += 1
            if count == 6:
                raise StopIteration
        self.exercise(step)
        self.assertEqual(self.commands, [('modprobe', 'm10_otg_id')])

    def test_kernel_mismatch_does_not_load_modules(self):
        with patch.object(self.probe, 'kernel_matches', return_value=False), patch.object(self.probe, 'command', self.command), patch.object(self.probe, 'log'):
            self.probe.run()
        self.assertEqual(self.commands, [])

    def test_role_failure_does_not_prevent_power_off(self):
        self.probe.STOP.write_text('0\n')
        self.probe.ROLE.unlink()
        with patch.object(self.probe, 'command', self.command), patch.object(self.probe, 'log'):
            with self.assertRaises(FileNotFoundError):
                self.probe.cleanup()
        self.assertFalse(self.probe.STOP.exists())


if __name__ == '__main__':
    unittest.main()
