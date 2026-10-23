import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pages_size', ROOT/'scripts/check-pages-size.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class PagesSizeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root/'out'
        self.output.mkdir()

    def test_all_public_sources_and_debug_packages_count_toward_limit(self):
        (self.output/'debug.apk').write_bytes(b'x'*50)
        (self.output/'sources').mkdir()
        (self.output/'sources/source.tar.xz').write_bytes(b'x'*70)
        extra = self.root/'docs'
        extra.mkdir()
        (extra/'guide.md').write_bytes(b'x'*30)
        result = u.measure(self.output, [extra], limit=u.RESERVE+150)
        self.assertEqual(result['status'], 'PAGES_SIZE_OK')
        self.assertEqual(result['bytes'], 150)
        self.assertEqual(u.measure(self.output, [extra], limit=u.RESERVE+149)['status'], 'PAGES_SIZE_EXCEEDED')
        self.assertTrue((self.output/'debug.apk').exists())
        self.assertTrue((self.output/'sources/source.tar.xz').exists())

    def test_symlinks_are_rejected_without_following_external_content(self):
        (self.output/'external').symlink_to(self.root/'outside')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            u.measure(self.output)
