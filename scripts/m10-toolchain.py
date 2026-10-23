#!/usr/bin/env python3
"""Select the official kernel's exact LLVM inside a disposable Alpine build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

from http_fetch import fetch


ROOT = Path(__file__).resolve().parents[1]
KEYS = '/usr/share/apk/keys/aarch64'
RELEASES = 'https://github.com/frenchfaso/rpd-apk/releases/download/'
REPOSITORY = 'https://dl-cdn.alpinelinux.org/alpine/edge/main'


def build_environment():
    if (os.geteuid() != 0 or platform.system() != 'Linux' or
            platform.machine() != 'aarch64' or
            not Path('/etc/alpine-release').is_file() or
            not any(Path(p).is_file() for p in ['/.dockerenv', '/run/.containerenv']) or
            os.environ.get('RPD_DISPOSABLE_BUILD') != '1'):
        raise ValueError('Exact LLVM selection requires a disposable root Alpine aarch64 container '
                         'with RPD_DISPOSABLE_BUILD=1')
    if not Path(KEYS).is_dir():
        raise ValueError('Trusted Alpine aarch64 package keys are unavailable')


def expected_toolchain(config):
    text = config.read_text()

    def field(name):
        values = re.findall(r'^' + name + r'=(.+)$', text, re.M)
        if len(values) != 1:
            raise ValueError('Expected one kernel ' + name)
        return values[0]

    encoded = field('CONFIG_CLANG_VERSION')
    if not re.fullmatch(r'\d{6}', encoded) or field('CONFIG_LLD_VERSION') != encoded:
        raise ValueError('Kernel Clang and LLD identities need review')
    value = int(encoded)
    major = value // 10000
    version = f'{major}.{value // 100 % 100}.{value % 100}'
    banner = 'Alpine clang version ' + version
    if not 20 <= major <= 99 or field('CONFIG_CC_VERSION_TEXT') != '"' + banner + '"':
        raise ValueError('Kernel compiler identity needs review')
    return major, version, banner


def manifest_packages(root, major, version):
    path = root / 'toolchains' / ('m10-llvm-' + version + '.json')
    if not path.is_file():
        raise ValueError('No reviewed exact LLVM manifest: ' + str(path))
    manifest = json.loads(path.read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'packages'} or
            manifest['version'] != version or not isinstance(manifest['packages'], list) or
            not manifest['packages']):
        raise ValueError('Exact LLVM manifest version/schema needs review')
    packages = manifest['packages']
    names = set()
    for package in packages:
        if (not isinstance(package, dict) or
                set(package) != {'name', 'version', 'url', 'sha512'} or
                not all(isinstance(v, str) for v in package.values())):
            raise ValueError('Exact LLVM package schema needs review')
        name = package['name']
        if (not re.fullmatch(r'(?:(?:clang|lld|llvm)' + str(major) +
                             r'(?:-[a-z0-9][a-z0-9+_.-]*)?|scudo-malloc)', name) or name in names or
                not re.fullmatch(re.escape(version) + r'-r\d+', package['version'])):
            raise ValueError('Unexpected exact LLVM package name/version: ' + name)
        filename = name + '-' + package['version'] + '.apk'
        url = RELEASES + 'm10-llvm-' + version + '/' + filename
        if package['url'] != url or not re.fullmatch(r'[0-9a-f]{128}', package['sha512']):
            raise ValueError('Unreviewed exact LLVM URL/digest: ' + name)
        names.add(name)
    if not {f'{name}{major}' for name in ['clang', 'lld', 'llvm']} <= names:
        raise ValueError('Exact LLVM package closure is incomplete')
    return packages


def apk(*args, repository=True):
    command = ['apk', '--arch', 'aarch64', '--keys-dir', KEYS,
               '--repositories-file', '/dev/null']
    if repository:
        command += ['--repository', REPOSITORY]
    subprocess.run([*command, *args], check=True)


def matches(major, version, banner):
    bindir = f'/usr/lib/llvm{major}/bin/'
    clang = subprocess.check_output([bindir + 'clang', '-dumpversion'], text=True).strip()
    identity = subprocess.check_output([bindir + 'clang', '--version'], text=True).splitlines()[0]
    linker = subprocess.check_output([bindir + 'ld.lld', '--version'], text=True).strip()
    if (clang != version or identity != banner or
            re.match(r'^LLD ' + re.escape(version) + r'(?:\s|$)', linker) is None):
        return False
    # Executable banners alone do not identify the split LLVM/Clang libraries.
    # --installed queries only the installed DB; -v emits name-version lines.
    packages = [f'clang{major}-libs', f'llvm{major}-libs']
    installed = subprocess.check_output(['apk', '--arch', 'aarch64', '--keys-dir', KEYS,
        '--repositories-file', '/dev/null', 'info', '--installed', '-v', *packages],
        text=True).splitlines()
    return len(installed) == len(packages) and all(
        sum(re.fullmatch(re.escape(name + '-' + version) + r'-r\d+', line) is not None
            for line in installed) == 1 for name in packages)


def install(root=ROOT):
    build_environment()
    major, version, banner = expected_toolchain(root / 'ports/rpd-backlight-m10/kernel.config')
    tools = [f'{name}{major}' for name in ['clang', 'lld', 'llvm']]
    apk('add', '--no-cache', '--upgrade', *tools)
    if matches(major, version, banner):
        print('Official kernel LLVM already matches: ' + version)
        return
    packages = manifest_packages(root, major, version)
    with tempfile.TemporaryDirectory(prefix='m10-llvm-') as temp:
        files = []
        for package in packages:
            data = fetch(package['url'])
            if hashlib.sha512(data).hexdigest() != package['sha512']:
                raise ValueError('Exact LLVM package checksum mismatch: ' + package['name'])
            path = Path(temp) / (package['name'] + '-' + package['version'] + '.apk')
            path.write_bytes(data)
            files.append(str(path))
        # Alpine's trusted target keys still authenticate every archived APK.
        # Explicit world constraints preserve the CFI compiler through abuild -r.
        pins = [p['name'] + '=' + p['version'] for p in packages]
        apk('add', '--no-network', *files, *pins, repository=False)
    if not matches(major, version, banner):
        raise ValueError('Installed LLVM does not match the official kernel compiler/linker')
    print('Installed exact official kernel LLVM: ' + version)


def restore(root=ROOT):
    build_environment()
    major, version, _ = expected_toolchain(root / 'ports/rpd-backlight-m10/kernel.config')
    names = {f'{name}{major}' for name in ['clang', 'lld', 'llvm']}
    if (root / 'toolchains' / ('m10-llvm-' + version + '.json')).is_file():
        names.update(p['name'] for p in manifest_packages(root, major, version))
    # Bare names replace the exact world constraints before normal userspace builds.
    apk('add', '--no-cache', '--upgrade', *sorted(names))
    print('Restored current Alpine LLVM for userspace builds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['install', 'restore'])
    args = parser.parse_args()
    {'install': install, 'restore': restore}[args.mode]()


if __name__ == '__main__':
    main()
