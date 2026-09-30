#!/usr/bin/env python3
"""Offline target-discovery and immutable-input fixtures; no build/download."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("verify", HERE / "verify-build.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


class TargetDiscovery(unittest.TestCase):
    def fixture(self):
        targets, queries = [], {}
        for unit in verify.UNITS:
            target = "obj/generated/" + Path(unit).stem + ".o"
            targets.append(target + ": cxx")
            queries[target] = target + ":\n  input: cxx\n    ../../" + unit + "\n"
        return "\n".join(targets), queries

    def test_derive_both_from_generated_graph(self):
        text, queries = self.fixture()
        rows = verify.select_targets(text, Path("/unused"), queries.__getitem__)
        self.assertEqual([row["source"] for row in rows], list(verify.UNITS))

    def test_same_basename_wrong_source_does_not_match(self):
        text, queries = self.fixture()
        first = next(iter(queries))
        queries[first] = queries[first].replace(verify.UNITS[0], "unrelated/" + Path(verify.UNITS[0]).name)
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            verify.select_targets(text, Path("/unused"), queries.__getitem__)

    def test_ambiguous_compilation_fails(self):
        text, queries = self.fixture()
        target = "obj/second/gpu_pre_sandbox_hook_linux.o"
        text += "\n" + target + ": cxx"
        queries[target] = "input: cxx\n  ../../" + verify.UNITS[0] + "\n"
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            verify.select_targets(text, Path("/unused"), queries.__getitem__)

    def test_missing_second_unit_fails(self):
        text, queries = self.fixture()
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            verify.select_targets(text.splitlines()[0], Path("/unused"), queries.__getitem__)

    def test_unexpected_target_syntax_fails(self):
        text, queries = self.fixture()
        original = next(iter(queries))
        malicious = "obj/unsafe;name/gpu_pre_sandbox_hook_linux.o"
        text = text.replace(original, malicious)
        queries[malicious] = queries.pop(original)
        with self.assertRaisesRegex(ValueError, "target syntax"):
            verify.select_targets(text, Path("/unused"), queries.__getitem__)

    def test_retained_candidate_inputs(self):
        verify.inputs(HERE.parent)

    def test_modified_patch_rejected(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "candidate"
            target.mkdir()
            manifest = json.loads((HERE.parent / "source-manifest.json").read_text())
            paths = [item["path"] for item in manifest["upstream_sources"]]
            paths += list(manifest["patches"]) + list(manifest["prepared_files"])
            for name in paths + ["source-manifest.json"]:
                output = target / name
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(HERE.parent / name, output)
            patch = target / next(iter(manifest["patches"]))
            patch.write_bytes(patch.read_bytes() + b"\nchanged\n")
            with self.assertRaisesRegex(ValueError, "input changed"):
                verify.inputs(target)

    def test_recipe_stage_matches_reviewed_candidate(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            port = Path(directory) / "aports/community/chromium"
            port.mkdir(parents=True)
            shutil.copyfile(HERE.parent / "upstream/aports/community/chromium/APKBUILD", port / "APKBUILD")
            report = verify.stage(HERE.parent, port)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual((port / "APKBUILD").read_bytes(),
                             (HERE.parent / "prepared/aports/community/chromium/APKBUILD").read_bytes())

    def test_changed_downloaded_recipe_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            port = Path(directory) / "aports/community/chromium"
            port.mkdir(parents=True)
            (port / "APKBUILD").write_text("unreviewed recipe\n")
            with self.assertRaisesRegex(ValueError, "exact pin"):
                verify.stage(HERE.parent, port)


class ResourceGuards(unittest.TestCase):
    def test_measured_runner_passes(self):
        self.assertEqual(verify.assess_resources("aarch64", 4, 15 * 2**30, 3 * 2**30,
                                                108 * 2**30)["status"], "PASS")

    def test_exact_minimum_passes(self):
        self.assertEqual(verify.assess_resources("aarch64", 4, 14 * 2**30, 3 * 2**30,
                                                100 * 2**30)["status"], "PASS")

    def test_each_capacity_guard_rejects(self):
        good = ["aarch64", 4, 15 * 2**30, 3 * 2**30, 108 * 2**30]
        for field, value in ((0, "x86_64"), (1, 2), (2, 13 * 2**30),
                             (3, 0), (4, 100 * 2**30 - 1)):
            with self.subTest(field=field):
                bad = good.copy()
                bad[field] = value
                self.assertEqual(verify.assess_resources(*bad)["status"], "FAIL")


class PositionalChecksums(unittest.TestCase):
    def test_original_checksums_preserved_in_source_order(self):
        original = verify.checksum_order((HERE.parent / "upstream/aports/community/chromium/APKBUILD").read_text())
        candidate = verify.checksum_order((HERE.parent / "prepared/aports/community/chromium/APKBUILD").read_text())
        self.assertEqual(candidate[:-1], original)
        self.assertEqual(candidate[-1][1], "chromium-linux-v4l2-decoder-broker.patch")

    def test_prepend_checksum_regression_rejected(self):
        recipe = (HERE.parent / "prepared/aports/community/chromium/APKBUILD").read_text()
        last = verify.checksum_order(recipe)[-1]
        entry = last[0] + "  " + last[1] + "\n"
        bad = recipe.replace(entry, "", 1).replace('sha512sums="\n', 'sha512sums="\n' + entry, 1)
        with self.assertRaisesRegex(ValueError, "positional order"):
            verify.checksum_order(bad)

    def fetch_fixture(self, reverse=False, corrupt=False):
        # Run the unchanged primary abuild algorithm, with local files and no
        # network or recipe evaluation. Its checksum filename words are retained
        # but default_fetch consumes the sums positionally, using shift 2.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = []
            for name, content in (("archive.tar.xz", b"archive fixture\n"),
                                  ("broker.patch", b"patch fixture\n")):
                (root / name).write_bytes(content)
                entries.append(hashlib.sha512(content).hexdigest() + "  " + name)
            if reverse:
                entries.reverse()
            if corrupt:
                (root / "archive.tar.xz").write_bytes(b"changed archive\n")
            sums = "\n".join(entries)
            script = '''
set -eu
. "$1"
startdir=$2
srcdir=$2/src
source="archive.tar.xz broker.patch"
sha512sums=$3
sumalgo=sha512
is_remote() { return 1; }
die() { echo "$*" >&2; exit 1; }
# macOS sha512sum does not accept a checksum stream on stdin. Keep the
# extracted abuild function unchanged and use its SHA512-compatible tool.
if [ "$(uname -s)" = Darwin ]; then
    sha512sum() { shasum -a 512 "$@"; }
fi
default_fetch
'''
            return subprocess.run(["sh", "-c", script, "fixture", str(HERE / "abuild-default-fetch.sh"),
                                   str(root), sums], capture_output=True, text=True)

    def test_actual_abuild_algorithm_accepts_matching_order(self):
        result = self.fetch_fixture()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_abuild_algorithm_rejects_same_entries_reordered(self):
        result = self.fetch_fixture(reverse=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("archive.tar.xz: FAILED", result.stdout)

    def test_actual_abuild_algorithm_rejects_corrupted_source(self):
        result = self.fetch_fixture(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("archive.tar.xz: FAILED", result.stdout)


if __name__ == "__main__":
    unittest.main()
