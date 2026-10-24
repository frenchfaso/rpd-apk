import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/webkit2gtk-6.0'
spec = importlib.util.spec_from_file_location('webkit_candidate', PORT / 'verify-build.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class WebKitConfigurationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.build = Path(temp.name)
        self.header = self.build / 'cmakeconfig.h'
        self.pc = self.build / 'Source/WebKit/webkitgtk-6.0.pc'
        self.pc.parent.mkdir(parents=True)
        self.pc.write_text('Name: WebKitGTK\nVersion: 2.54.2\n')
        (self.build / 'build.ninja').write_text(
            '  DEFINES = -DANGLE_ENABLE_OPENGL -DUSE_SYSTEM_EGL\n')
        self.definitions = {name: '1' for name in candidate.ENABLED}
        self.definitions.update({name: '0' for name in candidate.DISABLED})
        self.definitions['WEBKITGTK_API_VERSION'] = '"6.0"'
        self.save()

    def save(self):
        self.header.write_text('\n'.join(f'#define {name} {value}'
                                         for name, value in self.definitions.items()) + '\n')

    def test_effective_supported_configuration(self):
        result = candidate.configuration(self.build, '2.54.2')
        self.assertTrue(result['features']['ENABLE_BUBBLEWRAP_SANDBOX'])
        self.assertTrue(result['features']['USE_GSTREAMER_GL'])
        self.assertFalse(result['features']['USE_VULKAN'])

    def test_disabled_or_missing_required_feature_fails(self):
        for name in candidate.ENABLED:
            with self.subTest(feature=name):
                self.definitions[name] = '0'
                self.save()
                with self.assertRaisesRegex(ValueError, name):
                    candidate.configuration(self.build, '2.54.2')
                self.definitions[name] = '1'
        del self.definitions['ENABLE_BUBBLEWRAP_SANDBOX']
        self.save()
        with self.assertRaisesRegex(ValueError, 'ENABLE_BUBBLEWRAP_SANDBOX'):
            candidate.configuration(self.build, '2.54.2')

    def test_gtk3_or_old_source_version_fails(self):
        self.definitions['WEBKITGTK_API_VERSION'] = '"4.1"'
        self.save()
        with self.assertRaisesRegex(ValueError, 'GTK4'):
            candidate.configuration(self.build, '2.54.2')
        self.definitions['WEBKITGTK_API_VERSION'] = '"6.0"'
        self.save()
        self.pc.write_text('Version: 2.48.1\n')
        with self.assertRaisesRegex(ValueError, 'version'):
            candidate.configuration(self.build, '2.54.2')

    def test_missing_native_angle_backend_fails(self):
        for flags in ('-DANGLE_ENABLE_OPENGL', '-DUSE_SYSTEM_EGL'):
            with self.subTest(flags=flags):
                (self.build / 'build.ninja').write_text(f'  DEFINES = {flags}\n')
                with self.assertRaisesRegex(ValueError, 'native ANGLE OpenGL backend'):
                    candidate.configuration(self.build, '2.54.2')

    def test_source_order_and_local_bytes_match_abuild_checksums(self):
        recipe = (PORT / 'APKBUILD').read_text()
        version = re.search(r'^pkgver=(\S+)$', recipe, re.M)[1]
        sources = re.search(r'^source="([^"]+)"', recipe, re.M)[1].split()
        filenames = [source.rsplit('/', 1)[-1].replace('$pkgver', version)
                     for source in sources]
        rows = [line.split() for line in re.search(
            r'^sha512sums="([^"]+)"', recipe, re.M)[1].splitlines() if line.strip()]
        self.assertEqual(filenames, [name for digest, name in rows])
        for source, (digest, name) in zip(sources, rows):
            self.assertRegex(digest, r'^[0-9a-f]{128}$')
            if '://' not in source:
                self.assertEqual(hashlib.sha512((PORT / name).read_bytes()).hexdigest(), digest)
        provenance = json.loads((PORT / 'upstream.json').read_text())
        self.assertEqual(version, provenance['version'])
        self.assertEqual(rows[0][0], provenance['source']['sha512'])
        self.assertEqual(sources[0].replace('$pkgver', version), provenance['source']['url'])


@unittest.skipUnless(shutil.which('cc'), 'native C compiler is required for ABI probe tests')
class WebKitRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for prefix, soname in candidate.LIBRARIES.items():
            source = cls.root / (prefix + '.c')
            source.write_text('\n'.join(
                f'unsigned {prefix}_get_{part}_version(void) {{ return {number}; }}'
                for part, number in zip(('major', 'minor', 'micro'), (2, 54, 2))))
            shared_flag = '-dynamiclib' if sys.platform == 'darwin' else '-shared'
            subprocess.run(['cc', shared_flag, '-fPIC', str(source), '-o', str(cls.root / soname)],
                           check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_version_probe_loads_both_real_shared_libraries(self):
        result = candidate.runtime(self.root, '2.54.2')
        self.assertEqual(set(result['libraries']), set(candidate.LIBRARIES.values()))

    def test_version_probe_rejects_old_library(self):
        with self.assertRaisesRegex(ValueError, 'expected 2.48.1, got 2.54.2'):
            candidate.runtime(self.root, '2.48.1')

    def test_missing_required_soname_fails(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(OSError):
                candidate.runtime(Path(empty), '2.54.2')
