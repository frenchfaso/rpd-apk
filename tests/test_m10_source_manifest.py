import hashlib
from pathlib import Path
import re
import unittest


PORT = Path(__file__).resolve().parents[1] / 'ports/rpd-backlight-m10'


class SourceManifestTests(unittest.TestCase):
    def test_source_order_and_local_content_match_abuild_checksums(self):
        recipe = (PORT / 'APKBUILD').read_text()
        sources = re.search(r'^source="([^"]+)"', recipe, re.M)[1].split()
        filenames = [item.split('::')[0].rsplit('/', 1)[-1] for item in sources]
        checksums = re.search(r'^sha512sums="([^"]+)"', recipe, re.M)[1].splitlines()
        rows = [line.split() for line in checksums if line.strip()]
        # abuild associates each source with the checksum in the same position.
        self.assertEqual(filenames, [name for digest, name in rows])
        for source, (digest, name) in zip(sources, rows):
            if '://' not in source:
                with self.subTest(source=name):
                    self.assertEqual(hashlib.sha512((PORT / name).read_bytes()).hexdigest(), digest)
