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

    @patch.object(module, 'run', return_value='')
    @patch.object(module.DisplayPower, 'sleep_supported', return_value=True)
    def test_suspend_deadline_starts_at_blank_and_preserves_brightness(self, supported, run):
        with patch.object(module.time, 'monotonic', return_value=100):
            self.power.idle_off()
        with patch.object(module.time, 'monotonic', return_value=1299):
            self.assertFalse(self.power.idle_suspend(1200))
        with patch.object(module.time, 'monotonic', return_value=1300):
            self.assertTrue(self.power.idle_suspend(1200))
        self.power.before_sleep()
        self.power.after_resume()
        self.assertEqual((self.device / 'brightness').read_text(), '26')

    @patch.object(module, 'run', return_value='')
    @patch.object(module.DisplayPower, 'sleep_supported', return_value=True)
    def test_touch_cancels_pending_idle_suspend(self, supported, run):
        self.power.idle_off()
        self.power.idle_on()
        self.assertFalse(self.power.idle_suspend(1))
        # A subsequent deliberate Power press must still suspend.
        self.assertTrue(self.power.power())

    @patch.object(module, 'run', return_value='')
    @patch.object(module.DisplayPower, 'sleep_supported', return_value=True)
    def test_wake_key_release_does_not_resuspend_in_either_callback_order(self, supported, run):
        self.assertTrue(self.power.power())
        self.assertFalse(self.power.power())
        self.power.after_resume()
        self.assertFalse(self.power.power())
        self.assertEqual((self.device / 'brightness').read_text(), '26')
        with patch.object(module, 'boottime', return_value=module.boottime() + 3):
            self.assertTrue(self.power.power())

    @patch.object(module, 'run', return_value='[{"output":"Unknown-1","power-mode":"on"}]')
    @patch.object(module.DisplayPower, 'sleep_supported', return_value=False)
    def test_unavailable_retention_falls_back_to_blank(self, supported, run):
        self.assertFalse(self.power.power())
        self.assertEqual((self.device / 'brightness').read_text(), '0')
        self.power.idle_on()
        self.assertTrue(self.state.exists())

    @patch.object(module, 'run', return_value='')
    @patch.object(module.DisplayPower, 'sleep_supported', return_value=True)
    def test_logind_request_releases_lock_and_failure_restores_display(self, supported, run):
        config = self.root / 'screen-power.conf'
        config.write_text('[display]\noutput=Unknown-1\nbacklight=panel\n'
                          '[sleep]\nafter_blank_seconds=1200\n')
        def reject(*args, **kwargs):
            # PrepareForSleep callbacks must be able to acquire this same lock.
            with (self.root / 'rpd-screen-power.lock').open('w') as lock:
                module.fcntl.flock(lock, module.fcntl.LOCK_EX | module.fcntl.LOCK_NB)
            raise RuntimeError('Sleep inhibited')
        with patch.object(module, 'CONFIG', config), \
             patch.dict(module.os.environ, {'XDG_RUNTIME_DIR': str(self.root),
                                            'XDG_STATE_HOME': str(self.root / 'state')}), \
             patch.object(module.sys, 'argv', ['rpd-screen-power', 'power']), \
             patch.object(module.subprocess, 'run', side_effect=reject):
            with self.assertRaisesRegex(RuntimeError, 'Sleep inhibited'):
                module.main()
        self.assertEqual((self.device / 'brightness').read_text(), '26')
        self.assertFalse((self.root / 'state/rpd/screen-power.json').exists())

    def test_config_enables_suspend_binding(self):
        path = self.root / 'rc.xml'
        path.write_text('<labwc_config/>')
        module.configure(path, suspend=True)
        self.assertEqual(ET.parse(path).find('./keyboard/keybind/action').get('command'),
                         'rpd-screen-power power')

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

    @patch.object(module.subprocess, 'run')
    def test_manual_suspend_without_automatic_suspend(self, run):
        config = self.root / 'screen-power.conf'
        config.write_text('[display]\noutput=Unknown-1\nbacklight=panel\n'
                          '[sleep]\npower_button_suspend=true\nafter_blank_seconds=0\n')
        with patch.object(module, 'CONFIG', config), \
             patch.dict(module.os.environ, {'XDG_RUNTIME_DIR': str(self.root),
                                           'XDG_STATE_HOME': str(self.root)}), \
             patch.object(module.sys, 'argv', ['rpd-screen-power', 'power']), \
             patch.object(module.DisplayPower, 'power', return_value=True) as power:
            module.main()
            power.assert_called_once()
            self.assertEqual(run.call_args.args[0][-2:], ['b', 'false'])
            self.assertIn('Suspend', run.call_args.args[0])
            run.reset_mock()
            module.sys.argv = ['rpd-screen-power', 'idle-suspend']
            module.main()
            run.assert_not_called()
            path = self.root / 'rc.xml'
            path.write_text('<labwc_config/>')
            module.sys.argv = ['rpd-screen-power', 'configure', str(path)]
            module.main()
            command = ET.parse(path).find('keyboard/keybind/action').get('command')
            self.assertEqual(command, 'rpd-screen-power power')

    def test_namespaced_config_keeps_default_shortcuts(self):
        path = self.root / 'rc.xml'
        path.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><theme/></openbox_config>')
        module.configure(path)
        root = ET.parse(path).getroot()
        self.assertIsNotNone(root.find('{*}keyboard/{*}default'))
        self.assertEqual(root.find('{*}keyboard/{*}keybind/{*}action').get('command'), 'rpd-screen-power toggle')


if __name__ == '__main__':
    unittest.main()
