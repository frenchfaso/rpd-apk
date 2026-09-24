#!/usr/bin/env python3
"""Follow the published Alpine Mesa build, retaining the reviewed build recipe."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'ports/mesa'
API = 'https://gitlab.alpinelinux.org/api/v4/projects/alpine%2Faports/repository/'
PATCHES = ('adreno-504.patch', 'freedreno-msaa-gmem.patch')


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def field(text, name):
    return re.search(r'^' + re.escape(name) + r'=(.+)$', text, re.M)[1].strip('"')


def shape(text):
    text = re.sub(r'^(pkgver|pkgrel)=.*$', r'\1=<version>', text, flags=re.M)
    text = re.sub(r'^([0-9a-f]{128})  mesa-[^\n]+$',
                  '<checksum>  mesa-<version>.tar.xz', text, flags=re.M)
    return text


def customize(recipe, patches, revision):
    recipe = re.sub(r'^pkgrel=\d+$', 'pkgrel=' + str(revision), recipe, flags=re.M)
    recipe = recipe.replace('arch="all"', 'arch="aarch64"')
    # Local patches follow the upstream patches. Fail rather than silently omit
    # them if Alpine changes the source layout.
    assert recipe.count('\tllvm23.patch\n') == 1
    recipe = recipe.replace('\tllvm23.patch\n', '\tllvm23.patch\n' +
                            ''.join('\t' + name + '\n' for name in patches))
    assert recipe.rstrip().endswith('"')
    recipe = recipe.rstrip()[:-1] + ''.join(
        hashlib.sha512(data).hexdigest() + '  ' + name + '\n'
        for name, data in patches.items()) + '"\n'
    return recipe


def main():
    commit = json.loads(fetch(API + 'commits?path=main%2Fmesa&per_page=1'))[0]['id']
    recipe = fetch(API + 'files/main%2Fmesa%2FAPKBUILD/raw?ref=' + commit).decode()
    reference = (PORT / 'upstream-APKBUILD.reference').read_text()
    if recipe == reference:
        print('Reviewed Alpine Mesa recipe unchanged')
        return
    if shape(recipe) != shape(reference):
        raise ValueError('Alpine Mesa build recipe changed; review required')
    # Authenticate a published binary before following its source release.
    with tempfile.TemporaryDirectory() as temp:
        subprocess.run(['apk', '--arch', 'aarch64', '--repositories-file',
            '/dev/null', '--repository', 'https://dl-cdn.alpinelinux.org/alpine/edge/main',
            '--no-cache', 'fetch', '--from', 'none', '--output', temp, 'mesa'], check=True)
        package, = Path(temp).glob('mesa-*.apk')
        import gzip, io, tarfile
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(package.read_bytes())),
                          mode='r:', ignore_zeros=True) as tar:
            member = next(m for m in tar.getmembers() if m.name.removeprefix('./') == '.PKGINFO')
            info = tar.extractfile(member).read().decode()
    version = field(recipe, 'pkgver')
    upstream_revision = int(field(recipe, 'pkgrel'))
    expected = version + '-r' + str(upstream_revision)
    if not re.search(r'^pkgver = ' + re.escape(expected) + '$', info, re.M):
        raise ValueError('Published Alpine Mesa and source recipe differ; defer')
    current = (PORT / 'APKBUILD').read_text()
    comparison = subprocess.check_output(['apk', 'version', '-t', version,
                                          field(current, 'pkgver')], text=True).strip()
    if comparison == '<':
        raise ValueError('Mesa version regressed')
    revision = 1000 + upstream_revision
    if comparison == '=':
        revision = max(revision, int(field(current, 'pkgrel')) + 1)
    patches = {name: (PORT / name).read_bytes() for name in PATCHES}
    updated = customize(recipe, patches, revision)
    (PORT / 'APKBUILD').write_text(updated)
    (PORT / 'upstream-APKBUILD.reference').write_text(recipe)
    print('Prepared Mesa ' + expected + ' from Alpine ' + commit)


if __name__ == '__main__':
    main()
