import hashlib
from pathlib import Path
import re
import unittest


PORT = Path(__file__).resolve().parents[1] / 'ports/squeekboard'


class SqueekboardSourceTests(unittest.TestCase):
    def test_source_order_and_local_content_match_abuild_checksums(self):
        recipe = (PORT / 'APKBUILD').read_text()
        version = re.search(r'^pkgver=(.+)$', recipe, re.M)[1]
        sources = re.search(r'^source="([^"]+)"', recipe, re.M)[1].replace('$pkgver', version).split()
        filenames = [source.rsplit('/', 1)[-1] for source in sources]
        checksums = re.search(r'^sha512sums="([^"]+)"', recipe, re.M)[1]
        rows = [line.split() for line in checksums.splitlines() if line.strip()]
        self.assertEqual(filenames, [name for digest, name in rows])
        for source, (digest, name) in zip(sources, rows):
            if '://' not in source:
                with self.subTest(source=name):
                    self.assertEqual(hashlib.sha512((PORT / name).read_bytes()).hexdigest(), digest)
