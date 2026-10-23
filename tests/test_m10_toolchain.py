import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('m10_toolchain', ROOT / 'scripts/m10-toolchain.py')
toolchain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolchain)


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        port = self.root / 'ports/rpd-backlight-m10'
        port.mkdir(parents=True)
        self.config = port / 'kernel.config'
        self.config.write_text((ROOT / 'ports/rpd-backlight-m10/kernel.config').read_text())
        self.major, self.version, self.banner = toolchain.expected_toolchain(self.config)
        self.manifest_path = self.root / 'toolchains' / f'm10-llvm-{self.version}.json'
        self.manifest_path.parent.mkdir()
        self.packages = []
        self.contents = {}
        for tool in ['llvm', 'llvm-libs', 'clang', 'lld']:
            name = tool.replace('llvm-libs', f'llvm{self.major}-libs')
            if tool != 'llvm-libs':
                name += str(self.major)
            data = ('signed APK fixture ' + name).encode()
            version = self.version + '-r0'
            url = (toolchain.RELEASES + f'm10-llvm-{self.version}/'
                   f'{name}-{version}.apk')
            self.packages.append({'name': name, 'version': version, 'url': url,
                                  'sha512': hashlib.sha512(data).hexdigest()})
            self.contents[url] = data
        self.save_manifest()
        self.environment_patch = mock.patch.object(toolchain, 'build_environment')
        self.environment = self.environment_patch.start()
        self.run = mock.patch.object(toolchain.subprocess, 'run').start()
        self.output = mock.patch.object(toolchain.subprocess, 'check_output').start()
        self.fetch = mock.patch.object(toolchain, 'fetch', side_effect=self.contents.__getitem__).start()
        self.addCleanup(mock.patch.stopall)

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps({'version': self.version,
                                                  'packages': self.packages}))

    def probes(self, *versions):
        values = []
        for version in versions:
            values += [version, 'Alpine clang version ' + version + '\nTarget: aarch64',
                       'LLD ' + version + ' (compatible with GNU linkers)']
            if version == self.version:
                values += [f'clang{self.major}-libs-{version}-r0\n'
                           f'llvm{self.major}-libs-{version}-r0\n']
        self.output.side_effect = values

    def test_current_exact_compiler_needs_no_archive(self):
        self.probes(self.version)
        self.manifest_path.unlink()
        toolchain.install(self.root)
        self.fetch.assert_not_called()
        self.assertEqual(self.run.call_count, 1)

    def test_archived_closure_is_hashed_authenticated_and_pinned(self):
        self.probes('23.1.4', self.version)
        calls = []

        def inspect_install(command, check):
            calls.append(command)
            self.assertTrue(check)
            self.assertNotIn('--allow-untrusted', command)
            self.assertNotIn('--allow-downgrades', command)
            self.assertEqual(command[command.index('--keys-dir') + 1], toolchain.KEYS)
            self.assertEqual(command[command.index('--repositories-file') + 1], '/dev/null')
            if '--no-network' in command:
                self.assertNotIn('--repository', command)
                files = [Path(p) for p in command if p.endswith('.apk')]
                self.assertEqual(len(files), len(self.packages))
                for path in files:
                    self.assertTrue(path.is_file())
                for package in self.packages:
                    self.assertIn(package['name'] + '=' + package['version'], command)
            else:
                self.assertEqual(command.count('--repository'), 1)
                self.assertEqual(command[command.index('--repository') + 1],
                                 toolchain.REPOSITORY)

        self.run.side_effect = inspect_install
        toolchain.install(self.root)
        self.assertEqual(len(calls), 2)
        self.assertIn('--no-network', calls[1])
        self.assertEqual(self.fetch.call_count, len(self.packages))

    def test_checksum_failure_prevents_entire_downgrade(self):
        self.probes('23.1.4')
        self.contents[self.packages[-1]['url']] = b'modified APK'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            toolchain.install(self.root)
        self.assertEqual(self.run.call_count, 1)

    def test_alpine_signature_rejection_is_not_bypassed(self):
        self.probes('23.1.4')
        self.run.side_effect = [None, subprocess.CalledProcessError(1, ['apk'])]
        with self.assertRaises(subprocess.CalledProcessError):
            toolchain.install(self.root)
        self.assertEqual(self.run.call_count, 2)
        self.assertEqual(self.output.call_count, 3)
        for call in self.run.call_args_list:
            self.assertNotIn('--allow-untrusted', call.args[0])

    def test_unknown_version_fails_closed_without_archive(self):
        self.probes('23.1.4')
        self.manifest_path.unlink()
        with self.assertRaisesRegex(ValueError, 'No reviewed'):
            toolchain.install(self.root)
        self.fetch.assert_not_called()
        self.assertEqual(self.run.call_count, 1)

    def test_manifest_rejects_wrong_origin_filename_version_digest_and_closure(self):
        original = [dict(p) for p in self.packages]
        for field, value in [('url', 'https://example.test/clang.apk'),
                             ('url', self.packages[0]['url'] + '?unreviewed=1'),
                             ('version', '23.1.4-r0'), ('name', '../apk-tools'),
                             ('sha512', 'invalid')]:
            with self.subTest(field=field, value=value):
                self.packages = [dict(p) for p in original]
                self.packages[0][field] = value
                self.save_manifest()
                with self.assertRaises(ValueError):
                    toolchain.manifest_packages(self.root, self.major, self.version)
        self.packages = original[:-1]
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            toolchain.manifest_packages(self.root, self.major, self.version)

    def test_cfi_compiler_and_linker_identity_must_both_match(self):
        self.assertIn('CONFIG_CFI=y', self.config.read_text())
        for outputs in [[self.version, 'clang version ' + self.version,
                         'LLD ' + self.version],
                        [self.version, self.banner, 'LLD 23.1.4'],
                        ['23.1.4', self.banner, 'LLD ' + self.version]]:
            with self.subTest(outputs=outputs):
                self.output.side_effect = outputs
                self.assertFalse(toolchain.matches(self.major, self.version, self.banner))
        self.probes('23.1.4', '23.1.4')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            toolchain.install(self.root)

    def test_matching_banners_do_not_accept_mixed_llvm_libraries(self):
        for package in ['clang', 'llvm']:
            with self.subTest(package=package):
                self.probes(self.version)
                values = list(self.output.side_effect)
                values[-1] = values[-1].replace(
                    f'{package}{self.major}-libs-{self.version}-r0',
                    f'{package}{self.major}-libs-23.1.4-r0')
                self.output.side_effect = values
                self.assertFalse(toolchain.matches(self.major, self.version, self.banner))
        self.probes(self.version)
        values = list(self.output.side_effect)
        values[-1] = values[-1].replace('-r0', '-r3')
        self.output.side_effect = values
        self.assertTrue(toolchain.matches(self.major, self.version, self.banner))
        command = self.output.call_args.args[0]
        self.assertIn('--installed', command)
        self.assertEqual(command[command.index('--repositories-file') + 1], '/dev/null')
        self.assertNotIn('--repository', command)

    def test_kernel_identity_inconsistencies_are_rejected(self):
        original = self.config.read_text()
        for replacement in [original.replace('CONFIG_LLD_VERSION=230103',
                                             'CONFIG_LLD_VERSION=230104'),
                            original.replace('Alpine clang version', 'Other clang version')]:
            self.config.write_text(replacement)
            with self.assertRaisesRegex(ValueError, 'identity|identities'):
                toolchain.expected_toolchain(self.config)

    def test_restore_removes_all_exact_world_constraints(self):
        toolchain.restore(self.root)
        command = self.run.call_args.args[0]
        self.assertIn('--upgrade', command)
        self.assertEqual(command[command.index('--repositories-file') + 1], '/dev/null')
        self.assertEqual(command.count('--repository'), 1)
        self.assertEqual(command[command.index('--repository') + 1], toolchain.REPOSITORY)
        self.assertNotIn('--allow-downgrades', command)
        self.assertFalse(any('=' in argument for argument in command))
        for package in self.packages:
            self.assertIn(package['name'], command)
        self.fetch.assert_not_called()

    def test_current_exact_version_can_restore_without_archive(self):
        self.manifest_path.unlink()
        toolchain.restore(self.root)
        command = self.run.call_args.args[0]
        self.assertEqual(command[-3:], [f'clang{self.major}', f'lld{self.major}',
                                       f'llvm{self.major}'])

    def test_environment_guard_precedes_any_package_action(self):
        self.environment.side_effect = ValueError('unsafe environment')
        for mode in [toolchain.install, toolchain.restore]:
            with self.assertRaisesRegex(ValueError, 'unsafe environment'):
                mode(self.root)
        self.run.assert_not_called()
        self.fetch.assert_not_called()

    def test_real_environment_guard_rejects_host_nonroot_and_missing_opt_in(self):
        self.environment_patch.stop()
        with mock.patch.object(toolchain.os, 'geteuid', return_value=0), \
                mock.patch.object(toolchain.platform, 'system', return_value='Linux'), \
                mock.patch.object(toolchain.platform, 'machine', return_value='aarch64'), \
                mock.patch.object(toolchain.Path, 'is_file', return_value=True), \
                mock.patch.object(toolchain.Path, 'is_dir', return_value=True), \
                mock.patch.dict(toolchain.os.environ, {'RPD_DISPOSABLE_BUILD': '1'}):
            toolchain.build_environment()
            for target, value in [(toolchain.os.geteuid, 1000),
                                  (toolchain.platform.system, 'Darwin'),
                                  (toolchain.platform.machine, 'x86_64')]:
                with self.subTest(value=value):
                    previous = target.return_value
                    target.return_value = value
                    with self.assertRaisesRegex(ValueError, 'disposable'):
                        toolchain.build_environment()
                    target.return_value = previous
            with mock.patch.dict(toolchain.os.environ, {'RPD_DISPOSABLE_BUILD': ''}):
                with self.assertRaisesRegex(ValueError, 'disposable'):
                    toolchain.build_environment()


if __name__ == '__main__':
    unittest.main()
