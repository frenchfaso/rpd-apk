#!/usr/bin/env python3
"""Offline target-discovery and immutable-input fixtures; no build/download."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

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


class PatchPolicy(unittest.TestCase):
    def apply(self, name, mismatch=True, extra=(), long_input=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            first = "different-context" if mismatch else "expected-context"
            source.write_text(first + "\nold-value\nmatching-context\n")
            patch = root / name
            patch.write_text('''--- source.txt
+++ source.txt
@@ -1,3 +1,3 @@
 expected-context
-old-value
+new-value
 matching-context
''')
            args = ["sh", str(HERE / "patch-wrapper.sh"), "-p0", *extra]
            args += ["--input=" + str(patch)] if long_input else ["-i", str(patch)]
            result = subprocess.run(args, cwd=root, capture_output=True, text=True)
            return result, source.read_text()

    def test_official_patch_keeps_standard_recipe_context_policy(self):
        result, source = self.apply("unchanged-official.patch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("new-value", source)
        self.assertEqual(source, "different-context\nnew-value\nmatching-context\n")

    def test_each_candidate_patch_rejects_context_fuzz(self):
        for name in ("alpine-chromium-enable-v4l2-aarch64.patch",
                     "chromium-linux-v4l2-decoder-broker.patch"):
            with self.subTest(name=name):
                result, source = self.apply(name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("old-value", source)

    def test_candidate_exact_context_passes(self):
        result, source = self.apply("chromium-linux-v4l2-decoder-broker.patch", mismatch=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("new-value", source)
        self.assertNotIn("fuzz", result.stdout)

    def test_candidate_caller_cannot_override_fuzz_guard(self):
        result, source = self.apply("chromium-linux-v4l2-decoder-broker.patch", extra=("--fuzz=2",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old-value", source)

    def test_candidate_long_input_option_stays_strict(self):
        result, source = self.apply("chromium-linux-v4l2-decoder-broker.patch", long_input=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old-value", source)


class NativeGnTarget(unittest.TestCase):
    def failure_evidence(self, query_error=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "source/build/config/BUILDCONFIG.gn"
            config.parent.mkdir(parents=True)
            config.write_text("primary config fixture\n")
            diagnostic = root / "review/gn-arguments.json"
            values = {"target_cpu": 'target_cpu = "x64"\n',
                      "target_os": 'target_os = "linux"\n',
                      "use_v4l2_codec": "use_v4l2_codec = true\n", "use_vaapi": "use_vaapi = true\n"}

            def command(args, cwd=None):
                if args[-1] == "--version":
                    return "fixture-version\n"
                name = next(arg.removeprefix("--list=") for arg in args if arg.startswith("--list="))
                if query_error:
                    raise subprocess.CalledProcessError(2, args, output="query fixture error\n")
                return values[name]

            with mock.patch.object(verify, "run", side_effect=command), \
                    mock.patch.object(verify.platform, "system", return_value="Linux"), \
                    mock.patch.object(verify.platform, "machine", return_value="aarch64"):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    verify.targets(root / "source", diagnostic)
            self.assertEqual(diagnostic.with_name("gn-effective-buildconfig.gn").read_bytes(), config.read_bytes())
            return json.loads(diagnostic.read_text())

    def test_actual_gn_values_and_config_retained_before_failed_validation(self):
        evidence = self.failure_evidence()
        self.assertEqual(evidence["raw_gn_arguments"]["target_cpu"], 'target_cpu = "x64"\n')
        self.assertEqual(evidence["raw_gn_arguments"]["use_v4l2_codec"], "use_v4l2_codec = true\n")
        self.assertEqual(evidence["gn_version"], "fixture-version")
        self.assertEqual(evidence["status"], "UNPROVEN")

    def test_gn_query_error_is_retained_and_missing_values_unproven(self):
        evidence = self.failure_evidence(query_error=True)
        self.assertEqual(evidence["query_failed"], "target_cpu")
        self.assertEqual(evidence["raw_gn_arguments"]["target_cpu"], "query fixture error\n")
        self.assertIsNone(evidence["raw_gn_arguments"]["use_v4l2_codec"])
        self.assertEqual(evidence["status"], "FAIL")

    def test_exact_declared_argument_values(self):
        for name, text, expected in (("target_cpu", 'target_cpu=""\n', '""'),
                                     ("target_cpu", 'target_cpu = "arm64"\n', '"arm64"'),
                                     ("use_v4l2_codec", 'use_v4l2_codec = true\n', "true")):
            self.assertEqual(verify.gn_value(text, name), expected)

    def test_missing_and_duplicate_argument_fail(self):
        for text in ('unrelated=true\n', 'target_cpu="arm64"\ntarget_cpu="x64"\n'):
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                verify.gn_value(text, "target_cpu")

    def test_pinned_native_defaults_and_explicit_cpu_pass(self):
        for cpu in ('""', '"arm64"'):
            self.assertEqual(verify.native_cpu(cpu, '""', "Linux", "aarch64", verify.BUILD_CONFIG), "arm64")

    def test_non_native_target_and_changed_default_contract_fail(self):
        good = ['""', '""', "Linux", "aarch64", verify.BUILD_CONFIG]
        for field, value in ((0, '"x64"'), (1, '"android"'), (2, "Darwin"),
                             (3, "x86_64"), (4, "changed-buildconfig")):
            bad = good.copy()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify.native_cpu(*bad)

    def object_fixture(self, machine=183, bits=2):
        header = bytearray(20)
        header[:6] = b"\x7fELF" + bytes([bits, 1])
        import struct
        struct.pack_into("<H", header, 18, machine)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compiled.o"
            path.write_bytes(header)
            return verify.arm64_object(path)

    def test_actual_object_machine_aarch64(self):
        self.assertEqual(self.object_fixture(), "AARCH64")

    def test_non_arm64_object_rejected(self):
        with self.assertRaisesRegex(ValueError, "not AARCH64"):
            self.object_fixture(machine=62)

    def test_32bit_object_rejected(self):
        with self.assertRaisesRegex(ValueError, "not little-endian ELF64"):
            self.object_fixture(bits=1)


if __name__ == "__main__":
    unittest.main()
