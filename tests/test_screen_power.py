import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parents[1] / 'ports/rpd-session/rpd-screen-power'
loader = importlib.machinery.SourceFileLoader('screen_power', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class ScreenPowerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = self.root / 'backlight/panel'
        self.device.mkdir(parents=True)
        (self.device / 'brightness').write_text('26')
        (self.device / 'max_brightness').write_text('255')
        self.state = self.root / 'state/screen.json'
        self.patcher = patch.object(module, 'BACKLIGHTS', self.root / 'backlight')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.power = module.DisplayPower('Unknown-1', 'panel', self.state)

    @patch.object(module, 'run', return_value='')
    def test_repeated_off_preserves_original_brightness(self, run):
        self.power.off()
        self.power.off()
        self.assertEqual((self.device / 'brightness').read_text(), '0')
        self.power.on()
        self.assertEqual((self.device / 'brightness').read_text(), '26')
        self.assertFalse(self.state.exists())

    def test_failed_display_off_rolls_back_backlight(self):
        with patch.object(module, 'run', side_effect=[RuntimeError('DPMS failed'), '']):
            with self.assertRaisesRegex(RuntimeError, 'DPMS failed'):
                self.power.off()
        self.assertEqual((self.device / 'brightness').read_text(), '26')
        self.assertFalse(self.state.exists())

    def test_restore_after_compositor_exits(self):
        with patch.object(module, 'run', return_value=''):
            self.power.off()
        with patch.object(module, 'run', side_effect=RuntimeError('No compositor')):
            with self.assertRaises(RuntimeError):
                self.power.on()
        self.assertEqual((self.device / 'brightness').read_text(), '26')

    @patch.object(module, 'run', return_value='')
    def test_missing_kernel_module_does_not_block_display_control(self, run):
        power = module.DisplayPower('Unknown-1', 'missing', self.state)
        power.off()
        power.on()
        self.assertEqual(run.call_count, 2)
        self.assertFalse(self.state.exists())

    @patch.object(module, 'run', return_value='')
    def test_idle_resume_does_not_wake_manual_power_off(self, run):
        self.power.off()
        run.reset_mock()
        self.power.idle_on()
        run.assert_not_called()
        self.assertEqual((self.device / 'brightness').read_text(), '0')

    @patch.object(module, 'run', return_value='')
    def test_power_release_does_not_reblank_after_idle_wake(self, run):
        self.power.idle_off()
        self.power.idle_on()
        run.reset_mock()
        self.power.toggle()
        run.assert_not_called()
        self.assertEqual((self.device / 'brightness').read_text(), '26')

    def test_config_keeps_other_bindings_and_is_idempotent(self):
        path = self.root / 'rc.xml'
        path.write_text('<labwc_config><keyboard><default/><keybind key="C-A-t"><action name="Execute" command="lxterminal"/></keybind><keybind key="XF86PowerOff"><action name="Execute" command="pishutdown"/></keybind></keyboard></labwc_config>')
        module.configure(path)
        module.configure(path)
        root = ET.parse(path).getroot()
        binds = root.findall('./keyboard/keybind')
        self.assertEqual([item.get('key') for item in binds], ['C-A-t', 'XF86PowerOff'])
        self.assertEqual(binds[-1].get('onRelease'), 'yes')
        self.assertIsNotNone(root.find('./keyboard/default'))

    def test_namespaced_config_keeps_default_shortcuts(self):
        path = self.root / 'rc.xml'
        path.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><theme/></openbox_config>')
        module.configure(path)
        root = ET.parse(path).getroot()
        self.assertIsNotNone(root.find('{*}keyboard/{*}default'))
        self.assertEqual(root.find('{*}keyboard/{*}keybind/{*}action').get('command'), 'rpd-screen-power toggle')


if __name__ == '__main__':
    unittest.main()
