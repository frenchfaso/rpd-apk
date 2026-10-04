import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mesa_update', ROOT/'scripts/update-mesa.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class MesaUpdateTests(unittest.TestCase):
    def setUp(self):
        self.reference = (ROOT/'ports/mesa/upstream-APKBUILD.reference').read_text()

    def test_build_changes_require_review(self):
        for before, after in [('_llvmver=23', '_llvmver=24'),
                              ('-Dglx=dri', '-Dglx=disabled'),
                              ('\tllvm23.patch\n', '\tnew.patch\n')]:
            self.assertIn(before, self.reference)
            self.assertNotEqual(update.shape(self.reference),
                                update.shape(self.reference.replace(before, after)))

    def test_release_and_archive_hash_can_advance(self):
        newer = self.reference.replace('26.2.3', '26.2.4').replace('pkgrel=1\n', 'pkgrel=0\n')
        import re
        newer = re.sub(r'^[0-9a-f]{128}(  mesa-)', 'a'*128 + r'\1', newer, flags=re.M)
        self.assertEqual(update.shape(self.reference), update.shape(newer))

    def test_release_authentication_uses_target_architecture_keys(self):
        version = update.field(self.reference, 'pkgver')
        newer = self.reference.replace(version, version + '.1')
        with tempfile.TemporaryDirectory() as temp:
            port = Path(temp)
            (port/'upstream-APKBUILD.reference').write_text(self.reference)
            (port/'APKBUILD').write_text('unchanged')
            failure = subprocess.CalledProcessError(1, 'apk')
            with mock.patch.object(update, 'PORT', port), \
                 mock.patch.object(update, 'fetch', side_effect=[
                     json.dumps([{'id': 'commit'}]).encode(), newer.encode()]), \
                 mock.patch.object(update.subprocess, 'run', side_effect=failure) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    update.main()
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('--arch')+1], 'aarch64')
            self.assertEqual(command[command.index('--keys-dir')+1],
                             '/usr/share/apk/keys/aarch64')
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertNotIn('--allow-untrusted', command)
            self.assertEqual((port/'APKBUILD').read_text(), 'unchanged')
            self.assertEqual((port/'upstream-APKBUILD.reference').read_text(), self.reference)

    def test_upstream_recipe_and_software_fallback_preserved(self):
        patches = {name: (ROOT/'ports/mesa'/name).read_bytes() for name in update.PATCHES}
        current = (ROOT/'ports/mesa/APKBUILD').read_text()
        result = update.customize(self.reference, patches, int(update.field(current, 'pkgrel')))
        self.assertEqual(result, (ROOT/'ports/mesa/APKBUILD').read_text())
        self.assertIn('llvmpipe', result)
        self.assertEqual(result[result.index('prepare() {'):result.index('sha512sums=')],
                         self.reference[self.reference.index('prepare() {'):self.reference.index('sha512sums=')])
