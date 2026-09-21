#!/usr/bin/env python3
"""Replace APK v2 test signatures using Alpine's own abuild-sign.

Control and data gzip members remain byte-for-byte unchanged. No package code
is executed in this job. Format: https://wiki.alpinelinux.org/wiki/Apk_spec
"""
import hashlib, io, pathlib, subprocess, sys, tarfile, tempfile, zlib
root = pathlib.Path(__file__).resolve().parents[1]
key = pathlib.Path(sys.argv[1]).resolve()
pub = root / 'keys/rpd-apk.rsa.pub'
actual = subprocess.check_output(['openssl', 'rsa', '-in', str(key), '-pubout'], stderr=subprocess.DEVNULL)
if actual.strip() != pub.read_bytes().strip():
    raise SystemExit('Signing key does not match the pinned public key')

def members(blob):
    result = []
    while blob:
        dec = zlib.decompressobj(31)
        raw = dec.decompress(blob)
        if not dec.eof:
            raise ValueError('Incomplete gzip member')
        consumed = len(blob) - len(dec.unused_data)
        result.append((blob[:consumed], raw))
        blob = dec.unused_data
    return result

packages = sorted((root / 'out/aarch64').glob('*.apk'))
if not packages:
    raise SystemExit('No APK packages')
for pkg in packages:
    parts = members(pkg.read_bytes())
    if len(parts) != 3:
        raise ValueError(f'Expected signed APK v2: {pkg.name}')
    with tarfile.open(fileobj=io.BytesIO(parts[0][1])) as archive:
        if not all(x.name.startswith('.SIGN.') for x in archive.getmembers()):
            raise ValueError('Unexpected signature member')
    with tarfile.open(fileobj=io.BytesIO(parts[1][1])) as archive:
        info = archive.extractfile('.PKGINFO').read().decode()
    expected = next(line.split(' = ', 1)[1] for line in info.splitlines() if line.startswith('datahash = '))
    if hashlib.sha256(parts[2][0]).hexdigest() != expected:
        raise ValueError(f'Invalid data hash: {pkg.name}')
    with tempfile.TemporaryDirectory() as temp:
        control = pathlib.Path(temp) / 'control.tar.gz'
        control.write_bytes(parts[1][0])
        subprocess.run(['abuild-sign', '-k', str(key), '-p', str(pub), str(control)], check=True)
        pkg.write_bytes(control.read_bytes() + parts[2][0])
subprocess.run(['apk', '--keys-dir', str(root/'keys'), 'index', '--rewrite-arch', 'aarch64', '-o', str(root/'out/aarch64/APKINDEX.tar.gz'), *map(str, packages)], check=True)
subprocess.run(['abuild-sign', '-k', str(key), '-p', str(pub), str(root/'out/aarch64/APKINDEX.tar.gz')], check=True)
(root/'out/rpd-apk.rsa.pub').write_bytes(pub.read_bytes())
# Test-build keys must never be distributed as production trust anchors.
import shutil
shutil.rmtree(root/'out/keys', ignore_errors=True)
print(f'Signed {len(packages)} packages and index')
