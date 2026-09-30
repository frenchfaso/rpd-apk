#!/usr/bin/env python3
"""Optional Venus hook: guard the current official source, preserve prior composition."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import libfdt

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('venus_candidate', HERE / 'venus-candidate.py')
venus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(venus)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def installed_apk_version(package='linux-postmarketos-qcom-msm89x7'):
    # apk3's ordinary info -v NAME prints description/URL/size. Exists selects
    # only installed providers and its verbose form emits NAME-version.
    output = subprocess.check_output(['apk', 'info', '-e', '-v', package], text=True, timeout=20)
    lines = output.splitlines()
    prefix = package + '-'
    if len(lines) != 1 or not lines[0].startswith(prefix):
        raise ValueError('installed APK identity is not one exact package line')
    version = lines[0][len(prefix):]
    if not version or not version[0].isdigit() or any(char.isspace() for char in version):
        raise ValueError('installed APK version is malformed')
    return version


def identity(blob):
    fdt = libfdt.Fdt(blob)
    rows = [[path, [[name, value.hex()] for name, value in sorted(props.items())]]
            for path, props in sorted(venus.reserve.snapshot(fdt).items())]
    # Ignore binary packing/order, retain every property, memreserve and boot CPU.
    value = {'nodes': rows, 'memreserve': venus.reserve.memreserve(fdt),
             'header': list(struct.unpack_from('>10I', blob)[5:8])}
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def package_matches(data, qualification, apk, release=None):
    return (data.get('supported') is True and apk == qualification['apk'] == data.get('apk')
            and data.get('release') == qualification['release']
            and data.get('qualification_sha256') == sha((HERE / 'video-qualification.json').read_bytes())
            and (release is None or release == data['release']))


def private_files(data, directory):
    rows = data.get('modules', [])
    assert rows and {row['file'] for row in rows} >= {'venus-core.ko', 'venus-dec.ko'}, 'private decoder missing'
    assert all(row['file'] == Path(row['file']).name and row['file'].endswith('.ko')
               and row['file'] != 'venus-enc.ko' for row in rows), 'invalid private module inventory'
    for row in rows:
        assert sha((directory / row['file']).read_bytes()) == row['sha256'], row['file']


def official_matches(blob, qualification):
    assert identity(blob) == qualification['official_dtb_identity_sha256'], 'official DT changed'


def select(source, composed, directory, data, qualification, apk):
    if not package_matches(data, qualification, apk):
        return composed, 'optional video qualification does not match; prior composition retained'
    private_files(data, directory)
    official_matches(source, qualification)
    assert identity((directory / 'base.dtb').read_bytes()) == identity(source), 'build/current official DT differ'
    result, _ = venus.compose(composed, enable=True)
    return result, 'optional Venus decoder topology enabled'


def atomic_write(path, data):
    temporary = path.with_name(path.name + '.video.tmp')
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def update(source, target, directory, apk):
    try:
        # 95/96 must already have created CPU/audio/GPU composition. Never
        # substitute an old full tree if preceding hooks/current source are absent.
        old = target.read_bytes()
        data = json.loads((directory / 'kernel.json').read_text())
        qualification = json.loads((directory / 'video-qualification.json').read_text())
        result, message = select(source.read_bytes(), old, directory, data, qualification, apk)
        if result != old:
            atomic_write(target, result)
        print('rpd-video-m10: ' + message)
    except (OSError, ValueError, AssertionError, KeyError, libfdt.FdtException, subprocess.SubprocessError) as exc:
        print('rpd-video-m10: skip optional DT extension; prior composition retained: ' + str(exc), file=sys.stderr)
    return 0


def main():
    try:
        apk = installed_apk_version()
        return update(Path('/boot/dtbs/qcom/sdm429-lenovo-tbx505x.dtb'),
                      Path('/boot/dtbs/rpd/sdm429-lenovo-tbx505x.dtb'), HERE,
                      apk)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('rpd-video-m10: APK evidence unavailable; prior composition retained: ' + str(exc), file=sys.stderr)
        return 0


if __name__ == '__main__':
    sys.exit(main())
