#!/usr/bin/env python3
"""Exercise actual DT/build/ownership helpers using temporary files, no kernel writes."""
import contextlib
import importlib.util
import importlib.machinery
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import libfdt

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_loader(name.replace('-', '_'), importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(HERE / name)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy, build, loader = load('video-dtb.py'), load('build-video.py'), load('rpd-video-m10-load')
# CLI inputs are generated from current kernel in abuild; host uses saved official
# source and prior CPU/audio/GPU composition. No hardware is accessed here.
BASE = Path(sys.argv.pop(1)).read_bytes()
COMPOSED = Path(sys.argv.pop(1)).read_bytes()
CONFIG = Path(sys.argv.pop(1)).read_bytes()
QUAL = json.loads((HERE / 'video-qualification.json').read_text())
REAL_APK_API = '--real-apk-api' in sys.argv
if REAL_APK_API:
    sys.argv.remove('--real-apk-api')


class PackagingPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.data / 'video-qualification.json').write_bytes((HERE / 'video-qualification.json').read_bytes())
        (self.data / 'base.dtb').write_bytes(BASE)
        rows = []
        for name in ('venus-core.ko', 'venus-dec.ko'):
            content = b'Fixture data; not an ELF module and never passed to insmod: ' + name.encode()
            (self.data / name).write_bytes(content)
            rows.append({'file': name, 'sha256': policy.sha(content)})
        self.metadata = {'supported': True, 'apk': QUAL['apk'], 'release': QUAL['release'],
                         'qualification_sha256': policy.sha((HERE / 'video-qualification.json').read_bytes()), 'modules': rows}
        self.source, self.target = self.root / 'official.dtb', self.root / 'composed.dtb'
        self.source.write_bytes(BASE)
        self.target.write_bytes(COMPOSED)

    def update(self, apk=None):
        (self.data / 'kernel.json').write_text(json.dumps(self.metadata))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(policy.update(self.source, self.target, self.data, apk or QUAL['apk']), 0)
        self.assertFalse(self.target.with_name('composed.dtb.video.tmp').exists())
        return self.target.read_bytes() if self.target.exists() else None

    def test_matching_extends_only_venus_and_preserves_prior_composition(self):
        result = self.update()
        report = policy.venus.validate(COMPOSED, result, enable=True)
        self.assertTrue(report['unrelated_properties_unchanged'])
        self.assertEqual(loader.active_matches(result, BASE, policy)[policy.venus.CODEC]['status'], b'okay\0')

    def test_future_apk_preserves_exact_prior_bytes(self):
        self.assertEqual(self.update('7.1.4-r0'), COMPOSED)

    def test_unqualified_future_build_preserves_exact_prior_bytes(self):
        self.metadata['supported'] = False
        self.assertEqual(self.update(), COMPOSED)

    def test_wrong_official_dt_preserves_prior_composition(self):
        fdt = libfdt.Fdt(BASE)
        fdt.resize(fdt.totalsize() + 64)
        fdt.setprop(fdt.path_offset('/'), 'model', b'Changed official source\0')
        fdt.pack()
        self.source.write_bytes(bytes(fdt.as_bytearray()))
        self.assertEqual(self.update(), COMPOSED)

    def test_composed_is_not_accepted_as_official_source(self):
        self.source.write_bytes(COMPOSED)
        self.assertEqual(self.update(), COMPOSED)

    def test_missing_private_module_preserves_prior_bytes(self):
        (self.data / 'venus-dec.ko').unlink()
        self.assertEqual(self.update(), COMPOSED)

    def test_tampered_private_module_preserves_prior_bytes(self):
        (self.data / 'venus-core.ko').write_bytes(b'wrong object')
        self.assertEqual(self.update(), COMPOSED)

    def test_firmware_identity_and_absence_fail_before_module_operations(self):
        expected = {'venus.mdt': policy.sha(b'qualified stock firmware')}
        (self.data / 'venus.mdt').write_bytes(b'qualified stock firmware')
        loader.firmware_matches(self.data, expected, policy.sha)
        (self.data / 'venus.mdt').write_bytes(b'other firmware')
        with self.assertRaises(AssertionError):
            loader.firmware_matches(self.data, expected, policy.sha)
        (self.data / 'venus.mdt').unlink()
        with self.assertRaises(OSError):
            loader.firmware_matches(self.data, expected, policy.sha)

    def test_wrong_running_kernel_or_metadata_never_qualifies(self):
        self.assertFalse(policy.package_matches(self.metadata, QUAL, QUAL['apk'], '7.1.4-msm89x7'))
        self.metadata['release'] = '7.1.4-msm89x7'
        self.assertFalse(policy.package_matches(self.metadata, QUAL, QUAL['apk']))

    def test_exact_installed_identity_qualifies_only_pinned_apk_and_kernel(self):
        name = 'linux-postmarketos-qcom-msm89x7'
        for version, release, matches in [(QUAL['apk'], QUAL['release'], True),
                                          ('7.1.4-r0', QUAL['release'], False),
                                          (QUAL['apk'], '7.1.4-msm89x7', False)]:
            with mock.patch.object(policy.subprocess, 'check_output', return_value=name + '-' + version + '\n'):
                found = policy.installed_apk_version()
            self.assertEqual(policy.package_matches(self.metadata, QUAL, found, release), matches)

    def test_missing_installed_package_fails_before_any_target_write(self):
        with mock.patch.object(policy.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, ['apk'])):
            with self.assertRaises(subprocess.CalledProcessError):
                policy.installed_apk_version()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(policy.main(), 0)
        self.assertEqual(self.target.read_bytes(), COMPOSED)

    def test_query_timeout_preserves_prior_composition(self):
        with mock.patch.object(policy.subprocess, 'check_output', side_effect=subprocess.TimeoutExpired(['apk'], 20)):
            with self.assertRaises(subprocess.TimeoutExpired):
                policy.installed_apk_version()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(policy.main(), 0)
        self.assertEqual(self.target.read_bytes(), COMPOSED)

    def test_missing_apk_executable_preserves_prior_composition(self):
        with mock.patch.object(policy.subprocess, 'check_output', side_effect=FileNotFoundError('apk unavailable')):
            with self.assertRaises(FileNotFoundError):
                policy.installed_apk_version()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(policy.main(), 0)
        self.assertEqual(self.target.read_bytes(), COMPOSED)

    def test_malformed_multiline_and_descriptive_query_output_fail_closed(self):
        name = 'linux-postmarketos-qcom-msm89x7'
        for output in ('', QUAL['apk'] + '\n', name + ': package description\n',
                       name + '-' + QUAL['apk'] + '\n' + name + '-7.1.4-r0\n',
                       name + '-' + QUAL['apk'] + '\n\n', name + '-\n',
                       name + '-' + QUAL['apk'] + ' extra\n', 'other-package-' + QUAL['apk'] + '\n'):
            with self.subTest(output=output):
                with mock.patch.object(policy.subprocess, 'check_output', return_value=output):
                    with self.assertRaises(ValueError):
                        policy.installed_apk_version()
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(policy.main(), 0)
                self.assertEqual(self.target.read_bytes(), COMPOSED)

    def test_updater_cannot_implicitly_qualify_new_sources(self):
        self.assertTrue(build.eligible(QUAL, QUAL['apk'], QUAL['release'], CONFIG, BASE))
        for apk, release, config, base in [('7.1.4-r0', '7.1.4-msm89x7', CONFIG, BASE),
                                          (QUAL['apk'], QUAL['release'], CONFIG + b'\n# changed\n', BASE),
                                          (QUAL['apk'], QUAL['release'], CONFIG, COMPOSED)]:
            self.assertFalse(build.eligible(QUAL, apk, release, config, base))
        # Tracking replaces version literals in APKBUILD only; the separately
        # checksummed qualification source is not part of that replacement.
        self.assertEqual(QUAL['apk'], '7.1.3-r0')

    def test_missing_previous_hook_output_creates_no_old_tree(self):
        self.target.unlink()
        self.update()
        self.assertFalse(self.target.exists())

    def test_uninstall_recomposition_preserves_other_features(self):
        enabled = self.update()
        self.assertNotEqual(enabled, COMPOSED)
        # Subsequent 95/96 recomposition is the input to removed hook 97. A future
        # disabled video payload must keep that current result byte for byte.
        self.target.write_bytes(COMPOSED)
        self.metadata['supported'] = False
        self.assertEqual(self.update(), COMPOSED)


class DriverOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.device = Path(self.tmp.name) / '1d00000.venus'
        self.driver = Path(self.tmp.name) / 'qcom-venus'
        self.device.mkdir()
        self.driver.mkdir()
        self.override = self.device / 'driver_override'
        self.override.write_text('(null)\n')
        self.core_loaded = self.decoder_registered = False

    def core(self):
        self.assertEqual(self.override.read_text().strip(), loader.HOLD)
        self.assertFalse((self.device / 'driver').exists())
        self.core_loaded = True

    def decoder(self):
        self.assertTrue(self.core_loaded, 'decoder imports require registered core exports')
        self.assertFalse((self.device / 'driver').exists(), 'parent must not have created child yet')
        self.decoder_registered = True

    def bind(self):
        self.assertTrue(self.decoder_registered, 'private decoder must own child before first parent probe')
        self.assertTrue(loader.empty_override(self.override.read_text()))
        (self.device / 'driver').symlink_to(self.driver)

    def run_load(self, core=None, decoder=None):
        loader.hold_and_bind(self.device, self.driver, core or self.core, decoder or self.decoder,
                             lambda: self.core_loaded, bind=self.bind)

    def test_decoder_registered_before_first_parent_bind(self):
        self.run_load()
        self.assertTrue(self.decoder_registered)
        self.assertTrue(loader.empty_override(self.override.read_text()))

    def test_decoder_failure_releases_owned_hold_without_unload_or_bind(self):
        def failed():
            self.assertTrue(self.core_loaded)
            raise OSError('fixture: decoder insmod failed')
        with self.assertRaises(OSError):
            self.run_load(decoder=failed)
        self.assertTrue(self.core_loaded, 'partial live module stays intact')
        self.assertFalse((self.device / 'driver').exists())
        self.assertTrue(loader.empty_override(self.override.read_text()))

    def test_core_failure_releases_owned_hold(self):
        def failed():
            raise OSError('fixture: core insmod failed')
        with self.assertRaises(OSError):
            self.run_load(core=failed)
        self.assertTrue(loader.empty_override(self.override.read_text()))

    def test_prebound_driver_is_untouched(self):
        (self.device / 'driver').symlink_to(self.driver)
        with self.assertRaises(AssertionError):
            self.run_load()
        self.assertTrue((self.device / 'driver').exists())
        self.assertEqual(self.override.read_text(), '(null)\n')
        self.assertFalse(self.core_loaded)

    def test_live_module_is_not_replaced(self):
        self.core_loaded = True
        with self.assertRaises(AssertionError):
            self.run_load()
        self.assertEqual(self.override.read_text(), '(null)\n')

    def test_foreign_override_is_untouched(self):
        self.override.write_text('another-owner\n')
        with self.assertRaises(AssertionError):
            self.run_load()
        self.assertEqual(self.override.read_text(), 'another-owner\n')

    def test_interrupted_loader_restores_owned_override(self):
        def interrupted():
            raise InterruptedError('fixture: signal interrupted loader')
        with self.assertRaises(InterruptedError):
            self.run_load(core=interrupted)
        self.assertTrue(loader.empty_override(self.override.read_text()))

    def test_uninstall_recovers_orphaned_owned_hold_but_preserves_foreign(self):
        original = loader.DEVICE
        loader.DEVICE = self.device
        try:
            self.override.write_text(loader.HOLD + '\n')
            loader.restore_hold()
            self.assertTrue(loader.empty_override(self.override.read_text()))
            self.override.write_text('another-owner\n')
            loader.restore_hold()
            self.assertEqual(self.override.read_text(), 'another-owner\n')
        finally:
            loader.DEVICE = original

    def test_changed_owner_is_not_cleared_by_failure_cleanup(self):
        def changed():
            self.override.write_text('another-owner\n')
            raise OSError('fixture: owner changed')
        with self.assertRaises(OSError):
            self.run_load(core=changed)
        self.assertEqual(self.override.read_text(), 'another-owner\n')


if __name__ == '__main__':
    if REAL_APK_API:
        # Genuine installed Python package exercises the exact APK CLI boundary;
        # no fake kernel package/database is created for this software fixture.
        name = 'python3'
        version = policy.installed_apk_version(name)
        subprocess.run(['apk', 'info', '-e', name + '=' + version], check=True, stdout=subprocess.DEVNULL)
        assert subprocess.run(['apk', 'info', '-e', name + '=0.0.0-r0'], stdout=subprocess.DEVNULL).returncode != 0
        try:
            policy.installed_apk_version('rpd-video-api-nonexistent-qualification')
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError('absent package accepted by real installed query')
        old = subprocess.check_output(['apk', 'info', '-v', name], text=True)
        assert old != name + '-' + version + '\n', 'retain regression against descriptive API'
        print(json.dumps({'real_apk_api': 'PASS', 'apk_version': subprocess.check_output(['apk', '--version'], text=True).strip(),
                          'genuine_installed_package': name + '-' + version,
                          'exact_version_constraint_pass': True, 'wrong_version_and_absent_rejected': True,
                          'ordinary_verbose_info_is_descriptive': True}), flush=True)
    unittest.main()
