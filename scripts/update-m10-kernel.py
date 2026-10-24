#!/usr/bin/env python3
"""Authenticate the official kernel without replacing reviewed provider pins.

New releases are reported for review. Never execute upstream APKBUILD or mutate
ports/the provider lock. Run --validate-local without apk or network access.
"""
import argparse
import gzip
import hashlib
import io
import json
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile

from http_fetch import fetch

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = 'linux-postmarketos-qcom-msm89x7'
REPO = 'https://mirror.postmarketos.org/postmarketos/main'
RECIPE = ('https://gitlab.postmarketos.org/postmarketOS/pmaports/-/raw/main/'
          'device/testing/' + PACKAGE + '/APKBUILD')
VERSION = r'\d+(?:\.\d+)+-r\d+'


def field(text, name, separator='='):
    values = re.findall(r'^' + re.escape(name + separator) + r'(.+)$', text, re.M)
    if len(values) != 1:
        raise ValueError('Expected one field: ' + name)
    value = values[0]
    if value[:1] in ('"', "'") and value[-1:] == value[:1]:
        value = value[1:-1]
    return value


def digest(data, algorithm='sha256'):
    return hashlib.new(algorithm, data).hexdigest()


def checksum(recipe, name):
    values = re.findall(r'^([0-9a-f]{128})  ' + re.escape(name) + '$', recipe, re.M)
    if len(values) != 1:
        raise ValueError('Expected one source checksum: ' + name)
    return values[0]


def validate_local(root=None):
    root = ROOT if root is None else pathlib.Path(root)
    lock = json.loads((root / 'm10-kernel.lock.json').read_text())
    if (lock['schema'] != 1 or lock['package'] != PACKAGE or lock['arch'] != 'aarch64'
            or lock['provider'] not in ('official', 'rpd-security-overlay')):
        raise ValueError('Kernel provider policy requires review')
    base, effective = lock['upstream_base'], lock['effective']
    for version in (base['apk_version'], effective['apk_version']):
        if not re.fullmatch(VERSION, version):
            raise ValueError('Kernel version format requires review: ' + version)
    if lock['provider'] == 'official' and base['apk_version'] != effective['apk_version']:
        raise ValueError('Official provider differs from effective kernel')
    if base['apk_version'].split('-r')[0] != effective['apk_version'].split('-r')[0]:
        raise ValueError('Overlay and upstream base kernel versions differ')
    if (lock['provider'] == 'rpd-security-overlay' and
            int(effective['apk_version'].split('-r')[1]) <= int(base['apk_version'].split('-r')[1])):
        raise ValueError('Overlay revision must exceed its official base')
    module = root / 'ports/rpd-backlight-m10'
    kernel = root / 'ports' / PACKAGE
    reference = (module / 'upstream-APKBUILD.reference').read_bytes()
    config = (module / 'kernel.config').read_bytes()
    if digest(reference) != base['recipe_sha256']:
        raise ValueError('Reviewed official recipe identity differs from lock')
    if digest(config) != base['config_sha256']:
        raise ValueError('Reviewed official config identity differs from lock')
    if not re.fullmatch(r'[0-9a-f]{64}', base['apk_data_sha256']):
        raise ValueError('Official APK payload identity requires review')
    recipe = reference.decode()
    if field(recipe, 'pkgver') + '-r' + field(recipe, 'pkgrel') != base['apk_version']:
        raise ValueError('Reviewed recipe version differs from upstream base')
    if checksum(recipe, base['source_archive']) != base['source_sha512']:
        raise ValueError('Reviewed official source identity differs from lock')
    provenance = lock['security_manifest']
    if provenance['path'] != 'ports/' + PACKAGE + '/security-fixes.json':
        raise ValueError('Unexpected security manifest path')
    manifest_bytes = (root / provenance['path']).read_bytes()
    if digest(manifest_bytes) != provenance['sha256']:
        raise ValueError('Reviewed security manifest identity differs from lock')
    manifest = json.loads(manifest_bytes)
    if (manifest['kernel_package'] != PACKAGE
            or manifest['kernel_apk_version'] != effective['apk_version']
            or manifest['kernel_release'] != effective['kernelrelease']
            or manifest['base_board_archive_sha512'] != base['source_sha512']
            or manifest['canonical_config_sha256'] != base['config_sha256']):
        raise ValueError('Security manifest and kernel provider identities differ')
    fixes = manifest['fixes']
    if len(fixes) != 8 or len({fix['cve'] for fix in fixes}) != 8:
        raise ValueError('Expected all eight reviewed security fixes')
    module_recipe = (module / 'APKBUILD').read_text()
    loader = (module / 'rpd-backlight-m10-load').read_text()
    if (field(module_recipe, '_kernel_apk_version') != effective['apk_version']
            or field(loader, 'expected_apk') != effective['apk_version']
            or field(loader, 'expected') != effective['kernelrelease']
            or field(module_recipe, 'pkgver') + field(config.decode(), 'CONFIG_LOCALVERSION')
            != effective['kernelrelease']):
        raise ValueError('Module/loader and effective kernel identities differ')
    if checksum(module_recipe, 'kernel.config') != digest(config, 'sha512'):
        raise ValueError('Module config checksum differs')
    if checksum(module_recipe, 'rpd-backlight-m10-load') != digest(loader.encode(), 'sha512'):
        raise ValueError('Module loader checksum differs')
    module_sources = re.findall(r'^([0-9a-f]{128})  linux-v[^\n]+$', module_recipe, re.M)
    if module_sources != [base['source_sha512']]:
        raise ValueError('Module source differs from reviewed upstream base')
    ports = [module]
    if lock['provider'] == 'rpd-security-overlay':
        kernel_recipe = (kernel / 'APKBUILD').read_text()
        if field(kernel_recipe, 'pkgver') + '-r' + field(kernel_recipe, 'pkgrel') != effective['apk_version']:
            raise ValueError('Complete kernel recipe differs from effective APK')
        if checksum(kernel_recipe, base['source_archive']) != base['source_sha512']:
            raise ValueError('Complete kernel source differs from upstream base')
        if (kernel / 'config-postmarketos-qcom-msm89x7.aarch64').read_bytes() != config:
            raise ValueError('Complete kernel config differs from module config')
        ports.append(kernel)
    names = [fix['patch'] for fix in fixes]
    for port in ports:
        source = re.findall(r'^source="(.*?)"\n', (port / 'APKBUILD').read_text(), re.M | re.S)
        if len(source) != 1 or [name for name in source[0].split() if name.endswith('.patch')] != names:
            raise ValueError('Security patch source order differs from reviewed manifest')
    for number, fix in enumerate(fixes, 1):
        name = fix['patch']
        if name != f'{number:04d}-' + fix['cve'] + '.patch' or not re.fullmatch(r'CVE-\d{4}-\d+', fix['cve']):
            raise ValueError('Security patch order/name requires review')
        for port in ports:
            data = (port / name).read_bytes()
            if digest(data) != fix['sha256'] or checksum((port / 'APKBUILD').read_text(), name) != digest(data, 'sha512'):
                raise ValueError('Security patch identity differs: ' + name)
    return lock


def read_package(path):
    # APK v2 contains concatenated gzip/tar members. No files are extracted.
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(path.read_bytes())),
                      mode='r:', ignore_zeros=True) as archive:
        files = {}
        for member in archive:
            name = member.name.removeprefix('./')
            if name in ('.PKGINFO', 'boot/config'):
                if name in files or not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError('Invalid or duplicate APK identity member: ' + name)
                files[name] = archive.extractfile(member).read().decode()
    if set(files) != {'.PKGINFO', 'boot/config'}:
        raise ValueError('Required APK identity member absent')
    return files['.PKGINFO'], files['boot/config']


def check_upstream(lock):
    with tempfile.TemporaryDirectory() as temp:
        subprocess.run(['apk', '--arch', 'aarch64', '--keys-dir', str(ROOT / 'keys'),
            '--repositories-file', '/dev/null', '--repository', REPO,
            '--no-cache', 'fetch', '--from', 'none', '--output', temp, PACKAGE],
            check=True, stdout=sys.stderr)
        package, = pathlib.Path(temp).glob(PACKAGE + '-*.apk')
        # apk fetch authenticates the signed index and package control/data hashes.
        # The original builder's signature need not be the repository signing key.
        info, config = read_package(package)
    if field(info, 'pkgname', ' = ') != PACKAGE or field(info, 'arch', ' = ') != 'aarch64':
        raise ValueError('Published APK package/architecture differs')
    version = field(info, 'pkgver', ' = ')
    if not re.fullmatch(VERSION, version):
        raise ValueError('Kernel version format requires review: ' + version)
    payload_hash = field(info, 'datahash', ' = ')
    if not re.fullmatch(r'[0-9a-f]{64}', payload_hash):
        raise ValueError('Published APK payload identity requires review')
    recipe = fetch(RECIPE)
    text = recipe.decode()
    if field(text, 'pkgver') + '-r' + field(text, 'pkgrel') != version:
        raise ValueError('Published binary and upstream recipe differ; defer until matched')
    base = lock['upstream_base']
    result = {'provider': lock['provider'], 'official_base': base['apk_version'],
        'official_observed': version, 'effective_kernel': lock['effective']['apk_version'],
        'pins_preserved': True, 'security_fix_count': 8,
        'retained_upstream_series_maintained': json.loads(
            (ROOT / lock['security_manifest']['path']).read_text())['maintained_upstream_series']}
    if version == base['apk_version']:
        if (digest(recipe) != base['recipe_sha256']
                or digest(config.encode()) != base['config_sha256']
                or checksum(text, base['source_archive']) != base['source_sha512']
                or payload_hash != base['apk_data_sha256']):
            raise ValueError('Published kernel identity changed without an APK version bump')
        result.update(status='unchanged', message='Authenticated official base unchanged; reviewed provider and eight fixes retained.')
        return result
    comparison = subprocess.check_output(['apk', 'version', '-t', version,
                                           base['apk_version']], text=True).strip()
    if comparison != '>':
        raise ValueError('Published official kernel version regressed from its base')
    result.update(status='pending-review',
        message='New authenticated official kernel requires source/security/config/module review; existing pins retained.',
        observed_recipe_sha256=digest(recipe), observed_config_sha256=digest(config.encode()),
        observed_apk_data_sha256=payload_hash)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-local', action='store_true', help='validate lock and provider inputs without network or apk')
    args = parser.parse_args(argv)
    lock = validate_local()
    result = ({'status': 'local-verified', 'message': 'Reviewed kernel provider inputs match the lock.',
               'provider': lock['provider'], 'effective_kernel': lock['effective']['apk_version'],
               'official_base': lock['upstream_base']['apk_version'], 'security_fix_count': 8}
              if args.validate_local else check_upstream(lock))
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'error', 'message': str(error), 'pins_preserved': True}, indent=2))
        sys.exit(1)
