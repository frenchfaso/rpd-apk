#!/usr/bin/env python3
"""Authenticate same-revision native producer inputs before desktop compilation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
PRODUCERS = {
    'polkit': ['polkit'],
    'squeekboard': ['squeekboard'],
    'webkit': ['webkit2gtk-6.0'],
    'kernel': ['linux-postmarketos-qcom-msm89x7', 'rpd-cpu-topology-m10', 'rpd-backlight-m10'],
}


def recipe_packages(root, origin):
    text = (root / 'ports' / origin / 'APKBUILD').read_text()
    fields = {}
    for key in ['pkgname', '_pkgver', 'pkgver', 'pkgrel']:
        match = re.search(r'^' + key + r'=(.+)$', text, re.M)
        if match:
            value = match[1].strip('"')
            for name, replacement in fields.items():
                value = value.replace('${' + name + '}', replacement).replace('$' + name, replacement)
            fields[key] = value
    version = fields['pkgver'] + '-r' + fields['pkgrel']
    if not re.fullmatch(r'[0-9][0-9a-z._+]*-r[0-9]+', version):
        raise ValueError('Unreviewed recipe version expression: ' + origin)
    names = [fields['pkgname']]
    match = re.search(r'^subpackages="([^"]*)"', text, re.M)
    if match:
        names += [name.split(':')[0].replace('$pkgname', fields['pkgname'])
                  for name in match[1].split()]
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9+_.-]*', name) for name in names):
        raise ValueError('Unreviewed subpackage expression: ' + origin)
    return {name: (origin, version) for name in names}


def package_info(path):
    # Read concatenated APK v2 tar members without extracting package files.
    with gzip.open(path, 'rb') as stream:
        with tarfile.open(fileobj=stream, mode='r|', ignore_zeros=True) as archive:
            for entry in archive:
                if entry.name.removeprefix('./') == '.PKGINFO':
                    if not entry.isfile() or entry.size > 1024 * 1024:
                        raise ValueError('Invalid APK control metadata')
                    text = archive.extractfile(entry).read().decode()
                    break
            else:
                raise ValueError('Missing APK control metadata: ' + path.name)
    fields = {}
    for key in ['pkgname', 'pkgver', 'origin', 'arch', 'commit']:
        values = re.findall(r'^' + key + r' = (.*)$', text, re.M)
        if len(values) != 1:
            raise ValueError('Ambiguous APK field: ' + key)
        fields[key] = values[0]
    return fields


def regular_files(directory):
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError('Missing regular input directory: ' + str(directory))
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Artifact symlink is not permitted: ' + str(path))
        if path.is_file():
            yield path


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def preflight_copies(copies):
    planned = {}
    source_hashes = {}
    for source, destination in copies:
        if isinstance(source, bytes):
            expected = hashlib.sha256(source).hexdigest()
        else:
            if source.is_symlink() or not source.is_file():
                raise ValueError('Invalid artifact source: ' + str(source))
            if source not in source_hashes:
                source_hashes[source] = digest(source)
            expected = source_hashes[source]
        if destination in planned and planned[destination][1] != expected:
            raise ValueError('Conflicting artifact filename: ' + str(destination))
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file() or digest(destination) != expected:
                raise ValueError('Conflicting artifact filename: ' + str(destination))
        for parent in destination.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError('Invalid artifact destination parent: ' + str(parent))
        planned[destination] = (source, expected)
    for destination in planned:
        if any(parent in planned for parent in destination.parents):
            raise ValueError('Conflicting artifact parent path: ' + str(destination))
    return planned


def copy_preflighted(planned):
    for destination, (source, expected) in planned.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            if isinstance(source, bytes):
                destination.write_bytes(source)
            else:
                shutil.copyfile(source, destination)


def import_inputs(incoming, repository, keys, output, commit, root=ROOT):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected exact prepared source commit')
    pending = []
    packages = {}
    for producer, origins in PRODUCERS.items():
        source = incoming / producer
        if not source.is_dir() or source.is_symlink() or (source/'source-commit.txt').is_symlink():
            raise ValueError('Invalid producer input directory or receipt: ' + producer)
        if (source / 'source-commit.txt').read_text().strip() != commit:
            raise ValueError('Producer source revision differs: ' + producer)
        expected = {}
        for origin in origins:
            expected.update(recipe_packages(root, origin))
        public_keys = list(regular_files(source / 'keys'))
        if not public_keys or any(not re.fullmatch(r'[A-Za-z0-9@_.+-]+\.rsa\.pub', p.name)
                                  for p in public_keys):
            raise ValueError('Unexpected producer signing key files: ' + producer)
        files = list(regular_files(source / 'aarch64'))
        apks = [p for p in files if p.suffix == '.apk']
        if not apks:
            raise ValueError('Producer contains no APKs: ' + producer)
        subprocess.run(['apk', '--keys-dir', str(source / 'keys'), 'verify', *map(str, apks)], check=True)
        seen = set()
        for apk in apks:
            info = package_info(apk)
            name = info['pkgname']
            if name not in expected or (info['origin'], info['pkgver']) != expected[name]:
                raise ValueError('Unexpected producer package identity: ' + apk.name)
            if info['commit'] != commit or info['arch'] not in ['aarch64', 'noarch']:
                raise ValueError('Producer APK provenance/architecture differs: ' + apk.name)
            if apk.name != name + '-' + info['pkgver'] + '.apk' or name in seen or name in packages:
                raise ValueError('Duplicate or misleading producer APK: ' + apk.name)
            seen.add(name)
            packages[name] = {**info, 'producer': producer, 'sha256': digest(apk)}
        if seen != set(expected):
            raise ValueError('Producer package set is incomplete: ' + producer)
        sources = list(regular_files(source / 'sources'))
        if not sources:
            raise ValueError('Missing corresponding sources: ' + producer)
        pending.append((producer, source, public_keys, apks, sources))
    # Preflight every destination before mutating the repository or trust store.
    copies = []
    for producer, source, public_keys, apks, sources in pending:
        for public in public_keys:
            copies += [(public, keys / public.name), (public, output / 'keys' / public.name)]
        copies += [(apk, repository / apk.name) for apk in apks]
        copies += [(path, output / 'sources' / path.relative_to(source / 'sources')) for path in sources]
        for directory in ['proof', 'reports']:
            if (source / directory).is_dir():
                for path in regular_files(source / directory):
                    # Keep bounded proof, not multi-hour compiler logs or private keys.
                    if path.suffix in ['.json', '.config', '.symvers', '.h'] or path.name == 'CMakeCache.txt':
                        copies.append((path, output / 'build-inputs' / producer / directory / path.relative_to(source / directory)))
        for name in ['receipt.json', 'validation.txt', 'source-commit.txt']:
            if (source / name).is_file():
                copies.append((source / name, output / 'build-inputs' / producer / name))
    receipt = {'source_commit': commit, 'status': 'AUTHENTICATED_NATIVE_INPUTS', 'packages': packages}
    copies.append(((json.dumps(receipt, indent=2) + '\n').encode(), output / 'security-inputs.json'))
    copy_preflighted(preflight_copies(copies))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('incoming', type=Path)
    parser.add_argument('repository', type=Path)
    parser.add_argument('keys', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    receipt = import_inputs(args.incoming, args.repository, args.keys, args.output, args.commit)
    print('Authenticated', len(receipt['packages']), 'native producer APKs')


if __name__ == '__main__':
    main()
