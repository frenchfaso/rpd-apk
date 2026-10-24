import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('artifact_import', ROOT/'scripts/import-build-artifacts.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


def tar_member(name, data):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return gzip.compress(output.getvalue())


class ArtifactImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.incoming = self.base/'incoming'
        self.repository = self.base/'repo'
        self.keys = self.base/'keys'
        self.output = self.base/'out'
        self.commit = 'a'*40
        self.files = {}
        self.info = {}
        for producer, origins in u.PRODUCERS.items():
            source = self.incoming/producer
            for folder in ['keys', 'aarch64', 'sources']:
                (source/folder).mkdir(parents=True)
            (source/'source-commit.txt').write_text(self.commit+'\n')
            (source/'keys'/('test-'+producer+'.rsa.pub')).write_text('test-public-key-'+producer)
            (source/'sources/rpd-apk-packaging.tar.gz').write_bytes(b'identical reviewed sources')
            for origin in origins:
                for name, (expected_origin, version) in u.recipe_packages(ROOT, origin).items():
                    path = source/'aarch64'/(name+'-'+version+'.apk')
                    self.files[name] = path
                    self.info[name] = {'pkgname': name, 'pkgver': version,
                                       'origin': expected_origin, 'arch': 'aarch64',
                                       'commit': self.commit}
                    self.write_apk(name)
        self.verify = mock.patch.object(u.subprocess, 'run').start()
        self.addCleanup(mock.patch.stopall)

    def write_apk(self, name):
        control = ''.join(k+' = '+v+'\n' for k, v in self.info[name].items()).encode()
        self.files[name].write_bytes(tar_member('.SIGN.RSA.test.rsa.pub', b'signature')+
                                     tar_member('.PKGINFO', control)+tar_member('usr/file', b'data'))

    def destination_snapshot(self):
        result = {}
        for root in [self.keys, self.repository, self.output]:
            result[str(root)] = root.exists()
            if root.exists():
                for path in root.rglob('*'):
                    result[str(path)] = path.read_bytes() if path.is_file() else 'directory'
        return result

    def run_import(self):
        return u.import_inputs(self.incoming, self.repository, self.keys,
                               self.output, self.commit)

    def test_complete_same_revision_package_sets_are_authenticated_and_imported(self):
        result = self.run_import()
        self.assertEqual(set(result['packages']), set(self.files))
        self.assertEqual(self.verify.call_count, 4)
        for call in self.verify.call_args_list:
            self.assertEqual(call.args[0][:2], ['apk', '--keys-dir'])
            self.assertEqual(call.args[0][3], 'verify')
            self.assertTrue(call.kwargs['check'])
        for name, path in self.files.items():
            self.assertEqual((self.repository/path.name).read_bytes(), path.read_bytes())
            self.assertEqual(result['packages'][name]['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(len(list((self.output/'sources').iterdir())), 1)
        self.assertEqual(json.loads((self.output/'security-inputs.json').read_text())['source_commit'], self.commit)

    def test_wrong_producer_revision_fails_before_package_import(self):
        (self.incoming/'kernel/source-commit.txt').write_text('b'*40)
        with self.assertRaisesRegex(ValueError, 'revision differs'):
            self.run_import()
        self.assertFalse(self.repository.exists())

    def test_blank_apk_commit_is_rejected(self):
        self.info['squeekboard']['commit'] = ''
        self.write_apk('squeekboard')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.run_import()
        self.assertFalse(self.repository.exists())

    def test_version_must_match_the_reviewed_recipe(self):
        self.info['polkit']['pkgver'] = '9999127-r0'
        self.write_apk('polkit')
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.run_import()

    def test_missing_split_package_is_rejected(self):
        self.files['squeekboard-systemd'].unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.run_import()

    def test_native_signature_verification_failure_is_fatal(self):
        self.verify.side_effect = subprocess.CalledProcessError(1, ['apk', 'verify'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_import()
        self.assertFalse(self.repository.exists())

    def test_symlink_in_corresponding_sources_is_rejected(self):
        source = self.incoming/'polkit/sources'
        (source/'outside.tar.gz').symlink_to(self.base/'outside')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_import()

    def test_distinct_keys_with_the_same_filename_are_rejected(self):
        original = self.incoming/'squeekboard/keys/test-squeekboard.rsa.pub'
        original.rename(original.with_name('test-polkit.rsa.pub'))
        before = self.destination_snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting artifact'):
            self.run_import()
        self.assertEqual(self.destination_snapshot(), before)

    def test_different_corresponding_sources_with_the_same_name_are_rejected(self):
        (self.incoming/'kernel/sources/rpd-apk-packaging.tar.gz').write_bytes(b'unreviewed different sources')
        before = self.destination_snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting artifact'):
            self.run_import()
        self.assertEqual(self.destination_snapshot(), before)

    def test_existing_destination_collision_preserves_all_destination_trees(self):
        self.output.mkdir()
        (self.output/'sources').mkdir()
        existing = self.output/'sources/rpd-apk-packaging.tar.gz'
        existing.write_bytes(b'existing different source archive')
        self.keys.mkdir()
        (self.keys/'existing.rsa.pub').write_bytes(b'existing trust anchor')
        before = self.destination_snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting artifact'):
            self.run_import()
        self.assertEqual(self.destination_snapshot(), before)

    def test_identical_existing_inputs_can_be_imported_without_changes(self):
        self.run_import()
        before = self.destination_snapshot()
        self.run_import()
        self.assertEqual(self.destination_snapshot(), before)

    def test_planned_file_directory_conflict_preserves_destinations(self):
        (self.incoming/'polkit/sources/nested').write_bytes(b'file')
        directory = self.incoming/'kernel/sources/nested'
        directory.mkdir()
        (directory/'source.tar.gz').write_bytes(b'nested source')
        before = self.destination_snapshot()
        with self.assertRaisesRegex(ValueError, 'Conflicting artifact parent'):
            self.run_import()
        self.assertEqual(self.destination_snapshot(), before)
