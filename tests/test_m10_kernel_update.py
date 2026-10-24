import contextlib
import gzip
import importlib.util
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('updater', ROOT / 'scripts/update-m10-kernel.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class KernelUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'ports').mkdir()
        for name in ('rpd-backlight-m10', u.PACKAGE):
            shutil.copytree(ROOT / 'ports' / name, self.root / 'ports' / name,
                            symlinks=True, ignore=shutil.ignore_patterns('src', 'pkg', '__pycache__', '*.tar.*'))
        shutil.copy2(ROOT / 'm10-kernel.lock.json', self.root / 'm10-kernel.lock.json')
        self.lock = json.loads((self.root / 'm10-kernel.lock.json').read_text())
        self.port = self.root / 'ports/rpd-backlight-m10'
        self.recipe = (self.port / 'upstream-APKBUILD.reference').read_text()
        self.config = (self.port / 'kernel.config').read_text()
        self.version = self.lock['upstream_base']['apk_version']
        self.name, self.arch = u.PACKAGE, 'aarch64'
        self.datahash = self.lock['upstream_base']['apk_data_sha256']
        self.extra_info = ''
        self.run = patch.object(u.subprocess, 'run', side_effect=self.fake_run).start()
        self.compare = patch.object(u.subprocess, 'check_output', return_value='>\n').start()
        self.fetch = patch.object(u, 'fetch', side_effect=lambda _: self.recipe.encode()).start()
        patch.object(u, 'read_package', side_effect=lambda _: (self.package_info(), self.config)).start()
        patch.object(u, 'ROOT', self.root).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.temp.cleanup)

    def package_info(self):
        return (f'pkgname = {self.name}\npkgver = {self.version}\narch = {self.arch}\n'
                f'datahash = {self.datahash}\n' + self.extra_info)

    def fake_run(self, args, **kwargs):
        if 'fetch' in args:
            pathlib.Path(args[args.index('--output') + 1], u.PACKAGE + '-' + self.version + '.apk').touch()

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and not p.is_symlink()}

    def invoke(self, *args):
        before = self.snapshot()
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = u.main(list(args))
            self.assertEqual(json.loads(output.getvalue()), result)
            return result
        finally:
            self.assertEqual(self.snapshot(), before, 'tracker mutated reviewed inputs')

    def published_version(self, version):
        self.recipe = re.sub(r'^pkgver=.*$', 'pkgver=' + version.split('-r')[0], self.recipe, flags=re.M)
        self.recipe = re.sub(r'^pkgrel=.*$', 'pkgrel=' + version.split('-r')[1], self.recipe, flags=re.M)
        self.version = version

    def test_unchanged_base_retains_overlay_and_all_fixes_without_writes(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['official_base'], '7.1.3-r1')
        self.assertEqual(result['effective_kernel'], '7.1.3-r100')
        self.assertEqual(result['security_fix_count'], 8)
        self.assertFalse(result['retained_upstream_series_maintained'])
        self.compare.assert_not_called()
        self.fetch.assert_called_once_with(u.RECIPE)
        command = self.run.call_args.args[0]
        self.assertIn('--keys-dir', command)
        self.assertIn('--repositories-file', command)
        self.assertNotIn('--allow-untrusted', command)

    def test_local_validation_requires_no_apk_or_network(self):
        self.assertEqual(self.invoke('--validate-local')['status'], 'local-verified')
        self.run.assert_not_called()
        self.fetch.assert_not_called()

    def test_new_same_pkgver_revision_is_compared_to_base_not_overlay(self):
        self.published_version('7.1.3-r2')
        result = self.invoke()
        self.assertEqual(result['status'], 'pending-review')
        self.assertTrue(result['pins_preserved'])
        self.assertEqual(result['official_observed'], '7.1.3-r2')
        self.compare.assert_called_once_with(['apk', 'version', '-t', '7.1.3-r2', '7.1.3-r1'], text=True)

    def test_new_patch_or_series_stays_pending_even_with_changed_layout(self):
        for version in ('7.1.4-r0', '7.2.12-r0'):
            with self.subTest(version=version):
                self.published_version(version)
                self.recipe += '\n# unreviewed new recipe layout\n'
                self.config += '\nCONFIG_NEW_OPTION=y\n'
                result = self.invoke()
                self.assertEqual(result['status'], 'pending-review')
                self.assertEqual(result['effective_kernel'], '7.1.3-r100')
                self.assertIn('observed_recipe_sha256', result)

    def test_same_version_recipe_source_config_or_payload_change_is_rejected(self):
        original_recipe, original_config, original_hash = self.recipe, self.config, self.datahash
        variants = [('recipe', self.recipe + '\n# changed\n', self.config, self.datahash),
                    ('source', self.recipe.replace(self.lock['upstream_base']['source_sha512'], 'a' * 128), self.config, self.datahash),
                    ('config', self.recipe, self.config + '\nCONFIG_UNREVIEWED=y\n', self.datahash),
                    ('payload', self.recipe, self.config, 'b' * 64)]
        for name, self.recipe, self.config, self.datahash in variants:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'without an APK version bump'):
                self.invoke()
        self.recipe, self.config, self.datahash = original_recipe, original_config, original_hash

    def test_binary_recipe_version_mismatch_is_rejected(self):
        self.version = '7.1.3-r2'
        with self.assertRaisesRegex(ValueError, 'binary and upstream recipe differ'):
            self.invoke()

    def test_regression_compares_with_official_base(self):
        self.published_version('7.1.3-r0')
        self.compare.return_value = '<\n'
        with self.assertRaisesRegex(ValueError, 'regressed from its base'):
            self.invoke()
        self.assertEqual(self.compare.call_args.args[0][-1], '7.1.3-r1')

    def test_invalid_or_duplicate_published_identity_is_rejected(self):
        for name, arch, extra in [('wrong-kernel', 'aarch64', ''), (u.PACKAGE, 'x86_64', ''),
                                  (u.PACKAGE, 'aarch64', 'pkgver = 7.1.3-r1\n')]:
            self.name, self.arch, self.extra_info = name, arch, extra
            with self.subTest(name=name, arch=arch, extra=extra), self.assertRaises(ValueError):
                self.invoke()

    def test_authentication_failure_is_fatal_and_atomic(self):
        self.run.side_effect = subprocess.CalledProcessError(1, ['apk', 'fetch'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke()
        self.fetch.assert_not_called()

    def test_inconsistent_local_effective_identity_fails_before_network(self):
        path = self.port / 'rpd-backlight-m10-load'
        path.write_text(path.read_text().replace('expected_apk=7.1.3-r100', 'expected_apk=7.1.3-r1'))
        with self.assertRaisesRegex(ValueError, 'effective kernel identities differ'):
            self.invoke()
        self.run.assert_not_called()

    def test_changed_patch_or_manifest_is_rejected_before_network(self):
        manifest_path = self.root / self.lock['security_manifest']['path']
        manifest = json.loads(manifest_path.read_text())
        patch_path = self.port / manifest['fixes'][0]['patch']
        patch_path.write_bytes(patch_path.read_bytes() + b'\nchanged\n')
        with self.assertRaisesRegex(ValueError, 'Security patch identity differs'):
            self.invoke()
        self.run.assert_not_called()
        manifest_path.write_text(manifest_path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'manifest identity differs'):
            self.invoke()

    def test_all_eight_fixes_are_required_even_if_lock_digest_was_updated(self):
        manifest_path = self.root / self.lock['security_manifest']['path']
        manifest = json.loads(manifest_path.read_text())
        manifest['fixes'].pop()
        manifest_path.write_text(json.dumps(manifest))
        self.lock['security_manifest']['sha256'] = u.digest(manifest_path.read_bytes())
        (self.root / 'm10-kernel.lock.json').write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ValueError, 'all eight'):
            self.invoke()


class PackageIdentityTests(unittest.TestCase):
    def package(self, members):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, data in members:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        return gzip.compress(buffer.getvalue())

    def test_parser_reads_concatenated_apk_members_and_full_kernel_config(self):
        info, config = b'pkgver = 7.1.3-r1\n', b'CONFIG_TEST=y\n' * 10000
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'identity.apk'
            path.write_bytes(self.package([('.SIGN.RSA.fixture', b'signature fixture')]) +
                             self.package([('.PKGINFO', info)]) +
                             self.package([('boot/config', config)]))
            self.assertEqual(u.read_package(path), (info.decode(), config.decode()))

    def test_real_parser_rejects_duplicate_control_or_config(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'identity.apk'
            for duplicate in ('.PKGINFO', 'boot/config'):
                path.write_bytes(self.package([('.PKGINFO', b'pkgver = 1-r0\n'),
                                               ('boot/config', b'CONFIG_TEST=y\n'), (duplicate, b'changed\n')]))
                with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'duplicate'):
                    u.read_package(path)


if __name__ == '__main__':
    unittest.main()
