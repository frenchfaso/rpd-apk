#!/usr/bin/env python3
"""Audit genuine full-BSP inputs, runner capacity and built APK payloads."""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import struct
import subprocess
import tarfile

MANIFEST_SHA = 'bf24ace60055c30926bc5bc32447dd8572ed298a4a14323f34fbb352c9c1514f'
MODULES = {'mc.ko', 'videodev.ko', 'v4l2-mem2mem.ko', 'videobuf2-common.ko',
           'videobuf2-memops.ko', 'videobuf2-v4l2.ko', 'videobuf2-dma-contig.ko',
           'mdt_loader.ko', 'venus-core.ko', 'venus-dec.ko'}
PACKAGES = {'rpd-cpu-topology-m10': '0.1.0-r43', **dict.fromkeys(
    ('rpd-backlight-m10', 'rpd-gpu-m10', 'rpd-usb-otg-m10', 'rpd-battery-m10',
     'rpd-charger-m10', 'rpd-audio-m10', 'rpd-video-m10'), '7.1.3-r66')}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, report):
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def inputs(args):
    raw = args.manifest.read_bytes()
    assert sha(raw) == MANIFEST_SHA, 'final source fixture manifest changed'
    expected = json.loads(raw)['files']
    assert len(expected) == 108
    assert all(not PurePosixPath(p).is_absolute() and '..' not in PurePosixPath(p).parts
               and PurePosixPath(p).parts[0] == 'ports' for p in expected), 'unsafe manifest path'
    actual = {str(p.relative_to(args.fixture)): sha(p.read_bytes())
              for p in args.fixture.rglob('*') if p.is_file()}
    extra = actual.keys() - expected.keys()
    assert all('__pycache__' in PurePosixPath(p).parts and p.endswith('.pyc') for p in extra), 'unrecognized extra fixture file'
    assert {p: actual[p] for p in expected if p in actual} == expected, 'missing or changed full source fixture'
    assert not any(p.is_symlink() for p in args.fixture.rglob('*'))
    if args.stage:
        assert not (args.stage / 'ports').exists(), 'build ports already exist'
        for relative, digest in expected.items():
            source = args.fixture / relative
            assert sha(source.read_bytes()) == digest
            destination = args.stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    write(args.report, {'status': 'PASS', 'manifest_sha256': MANIFEST_SHA,
                        'files': expected, 'ignored_generated_cache': sorted(extra),
                        'stage': str(args.stage) if args.stage else None,
                        'bytes': sum((args.fixture / p).stat().st_size for p in expected)})


def resources(args):
    mem = {name: int(value.split()[0]) * 1024 for name, value in
           (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
    limits = []
    for path in ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory/memory.limit_in_bytes'):
        if Path(path).exists():
            value = Path(path).read_text().strip()
            if value.isdigit():
                limits.append(int(value))
    effective = min([mem['MemTotal'], *limits])
    report = {'architecture': platform.machine(), 'cpu_count': os.cpu_count(),
              'memory_bytes': mem['MemTotal'], 'effective_memory_bytes': effective,
              'free_disk_bytes': shutil.disk_usage(args.path).free,
              'gates': {'native_aarch64': platform.machine() == 'aarch64',
                        'four_cpus': os.cpu_count() >= 4,
                        'eight_gib_memory': effective >= 8 * 1024**3,
                        'twenty_gib_free': shutil.disk_usage(args.path).free >= 20 * 1024**3}}
    write(args.report, report)
    assert all(report['gates'].values()), 'insufficient runner capacity'


def archive_files(path):
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(path.read_bytes())),
                      mode='r:', ignore_zeros=True) as archive:
        files = {}
        for member in archive:
            name = member.name.removeprefix('./')
            assert not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
            if member.isfile():
                assert name not in files, ('duplicate APK file', name)
                files[name] = archive.extractfile(member).read()
        return files


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def elf(data, module=True):
    assert data[:6] == b'\x7fELF\x02\x01', 'not ELF64 little endian'
    assert struct.unpack_from('<H', data, 18)[0] == 183, 'not AArch64'
    kind = struct.unpack_from('<H', data, 16)[0]
    assert (kind == 1 if module else kind in (2, 3)), ('wrong ELF type', kind)


def artifacts(args):
    import libfdt
    result = args.report.parent
    payload = result / 'audit-payload'
    payload.mkdir()
    rows, names, package_data = [], set(), {}
    public = sorted(args.keys.glob('*.pub'))
    assert len(public) == 1, 'one ephemeral build public key required'
    for path in sorted(args.packages.glob('*.apk')):
        verify = subprocess.run(['apk', 'verify', '--keys-dir', str(args.keys), str(path)],
                                capture_output=True, text=True)
        assert verify.returncode == 0, (path.name, verify.stdout, verify.stderr)
        files = archive_files(path)
        fields = {}
        for line in files['.PKGINFO'].decode().splitlines():
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                fields.setdefault(key, []).append(value)
        name, version = fields['pkgname'][0], fields['pkgver'][0]
        assert name not in names and PACKAGES.get(name) == version, (name, version)
        assert fields['arch'][0] in ('aarch64', 'noarch')
        names.add(name)
        package_data[name] = files
        source = args.fixture / 'ports' / ('rpd-cpu-topology-m10' if name == 'rpd-cpu-topology-m10'
                                         else 'rpd-backlight-m10')
        for suffix in ('post-install', 'post-upgrade', 'pre-deinstall', 'post-deinstall'):
            script = source / (name + '.' + suffix)
            assert ('.' + suffix in files) == script.exists(), (name, suffix, 'script inventory')
            if script.exists():
                assert files['.' + suffix] == script.read_bytes(), (name, suffix, 'script bytes')
        for relative, data in files.items():
            if relative.startswith(('usr/', 'etc/')):
                destination = payload / relative
                assert not destination.exists(), ('overlapping BSP payload', relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        rows.append({'file': path.name, 'name': name, 'version': version,
                     'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes()),
                     'signature_verified': True, 'dependencies': fields.get('depend', [])})
    assert names == set(PACKAGES), ('incomplete output APK set', names)
    version = '7.1.3-r66'
    for dependent, dependency in (('rpd-video-m10', 'rpd-gpu-m10'),
                                 ('rpd-gpu-m10', 'rpd-audio-m10'),
                                 ('rpd-charger-m10', 'rpd-battery-m10')):
        assert ('depend = ' + dependency + '=' + version + '\n').encode() in package_data[dependent]['.PKGINFO']
    video = payload / 'usr/lib/rpd-video-m10'
    data = json.loads((video / 'kernel.json').read_text())
    policy = load('full_bsp_video', video / 'video-dtb.py')
    qualification = json.loads((video / 'video-qualification.json').read_text())
    assert data['supported'] is True and data['private_decoder_only'] is True
    assert data['release'] == qualification['release'] == '7.1.3-msm89x7'
    assert data['apk'] == qualification['apk'] == '7.1.3-r0'
    assert data['qualification_sha256'] == sha((video / 'video-qualification.json').read_bytes())
    assert data['normalized_config_sha256'] == qualification['normalized_config_sha256']
    assert data['base_identity_sha256'] == qualification['official_dtb_identity_sha256']
    assert {row['file'] for row in data['modules']} == MODULES and len(data['modules']) == 10
    assert not any(name.startswith('usr/lib/modules/') for name in package_data['rpd-video-m10'])
    assert not any('venus-enc' in name for name in package_data['rpd-video-m10'])
    imported = set()
    modules = []
    for row in data['modules']:
        path = video / row['file']
        binary = path.read_bytes()
        elf(binary)
        assert sha(binary) == row['sha256']
        for field in ('vermagic', 'depends', 'srcversion'):
            value = subprocess.check_output(['modinfo', '-F', field, str(path)], text=True).strip()
            assert value == row[field], (row['file'], field)
        assert row['vermagic'].split()[0] == data['release']
        symbols = subprocess.check_output(['/usr/lib/llvm22/bin/llvm-nm', '-u', str(path)], text=True)
        imported |= {words[-1] for line in symbols.splitlines() if
                     (words := line.split()) and words[0] == 'U'}
        modules.append(row)
    assert next(r for r in modules if r['file'] == 'venus-core.ko')['srcversion'] == '1907432261AFB6BFDB744CE'
    assert next(r for r in modules if r['file'] == 'venus-dec.ko')['srcversion'] == 'BF4EA388DA1A4F814AE224C'
    src = args.build / 'ports/rpd-backlight-m10/src'
    kernel = src / 'linux-7.1.3-r1'
    assert (kernel / 'include/config/kernel.release').read_text().strip() == data['release']
    config = (kernel / '.config').read_bytes().replace(b'CONFIG_CC_CAN_LINK=y\n', b'')
    assert sha(config) == qualification['normalized_config_sha256']
    exports = set()
    export_rows = []
    proof = result / 'kernel-proof'
    proof.mkdir()
    for index, path in enumerate((kernel / 'Module.symvers', kernel / 'vmlinux.symvers',
                 src / 'video-module/media/Module.symvers', src / 'video-module/mdt/Module.symvers',
                 src / 'video-module/venus-source/drivers/media/platform/qcom/venus/Module.symvers')):
        binary = path.read_bytes()
        exports |= {line.split()[1] for line in binary.decode().splitlines() if line.strip()}
        export_rows.append({'path': str(path.relative_to(src)), 'sha256': sha(binary)})
        (proof / (str(index) + '-Module.symvers')).write_bytes(binary)
    assert not imported - exports, ('unresolved strong imports', sorted(imported - exports))
    for name in ('core.c', 'vdec.c'):
        path = src / 'video-module/venus-source/drivers/media/platform/qcom/venus' / name
        assert sha(path.read_bytes()) == qualification['prepared_venus_' + ('core' if name == 'core.c' else 'vdec') + '_sha256']
        shutil.copyfile(path, proof / name)
    shutil.copyfile(kernel / '.config', proof / 'kernel.config')
    shutil.copyfile(src / 'video-module/kernel.json', proof / 'video-kernel.json')
    write(proof / 'strong-imports.json', sorted(imported))
    for name, files in package_data.items():
        for relative, binary in files.items():
            if relative.endswith('.ko'):
                elf(binary)
    required = {'rpd-backlight-m10': ['m10_firmware_backlight'],
                'rpd-usb-otg-m10': ['m10_otg_id', 'm10_otg_vbus'],
                'rpd-battery-m10': ['m10_battery', 'm10_adc5_battery'],
                'rpd-charger-m10': ['m10_charger'],
                'rpd-audio-m10': ['m10_audio_pmic', 'm10_wcd_analog', 'm10_speaker_amp']}
    for package, module_names in required.items():
        for name in module_names:
            relative = 'usr/lib/modules/7.1.3-msm89x7/extra/' + name + '.ko'
            assert relative in package_data[package], (package, relative)
    for name in ('msm.ko', 'ubwc_config.ko'):
        assert 'usr/lib/rpd-gpu-m10/' + name in package_data['rpd-gpu-m10']
    runtime_files = {
        'rpd-backlight-m10': ('usr/libexec/rpd-backlight-m10-load', 'usr/lib/systemd/system/rpd-backlight-m10.service'),
        'rpd-usb-otg-m10': ('usr/libexec/rpd-usb-otg-m10', 'usr/lib/systemd/system/rpd-usb-otg-m10.service',
                          'usr/lib/systemd/system-preset/80-rpd-usb-otg-m10.preset'),
        'rpd-battery-m10': ('usr/libexec/rpd-battery-m10-load', 'usr/lib/systemd/system/rpd-battery-m10.service',
                          'usr/lib/systemd/system-preset/80-rpd-battery-m10.preset'),
        'rpd-charger-m10': ('usr/libexec/rpd-charger-m10-load', 'usr/lib/systemd/system/rpd-charger-m10.service',
                          'usr/lib/systemd/system-preset/80-rpd-charger-m10.preset'),
        'rpd-audio-m10': ('usr/share/boot-deploy/hooks/95-rpd-audio-m10',
                        'usr/share/alsa/ucm2/conf.d/Lenovo-M10/Lenovo-M10.conf',
                        'usr/share/alsa/ucm2/Lenovo/M10/HiFi.conf',
                        'etc/wireplumber/wireplumber.conf.d/51-rpd-m10-audio.conf'),
        'rpd-gpu-m10': ('usr/libexec/rpd-gpu-m10-load', 'usr/lib/systemd/system/rpd-gpu-m10.service',
                      'usr/share/boot-deploy/hooks/96-rpd-gpu-m10', 'usr/share/mkinitfs/files/rpd-gpu-m10.files',
                      'etc/modprobe.d/rpd-gpu-m10.conf', 'usr/lib/rpd-gpu-m10/renderer.sh'),
        'rpd-video-m10': ('usr/libexec/rpd-video-m10-load', 'usr/lib/systemd/system/rpd-video-m10.service',
                        'usr/share/boot-deploy/hooks/97-rpd-video-m10',
                        'usr/lib/systemd/system-preset/80-rpd-video-m10.preset'),
        'rpd-cpu-topology-m10': ('usr/share/boot-deploy/hooks/90-rpd-cpu-topology-m10', 'etc/deviceinfo')}
    for package, paths in runtime_files.items():
        assert set(paths) <= package_data[package].keys(), ('missing BSP runtime files', package)
    elf((payload / 'usr/libexec/rpd-gpu-m10-probe').read_bytes(), module=False)
    linked = subprocess.check_output(['/usr/lib/llvm22/bin/llvm-readelf', '-d',
                                     str(payload / 'usr/libexec/rpd-gpu-m10-probe')], text=True)
    assert all(library in linked for library in ('libEGL.so', 'libGLESv2.so', 'libgbm.so'))
    topology = load('full_bsp_topology', payload / 'usr/lib/rpd-cpu-topology-m10/topology.py')
    gpu = load('full_bsp_gpu', payload / 'usr/lib/rpd-gpu-m10/gpu-dtb.py')
    gpu_data = json.loads((payload / 'usr/lib/rpd-gpu-m10/kernel.json').read_text())
    assert gpu_data['release'] == data['release'] and gpu_data['apk'] == data['apk'], 'GPU/video kernel identity differs'
    base = (video / 'base.dtb').read_bytes()
    assert policy.identity(base) == qualification['official_dtb_identity_sha256']
    assert base == (payload / 'usr/lib/rpd-audio-m10/base.dtb').read_bytes()
    assert base == (payload / 'usr/lib/rpd-gpu-m10/base.dtb').read_bytes()
    composed = topology.corrected((payload / 'usr/lib/rpd-audio-m10/audio.dtb').read_bytes())[0]
    composed = gpu.select(base, composed, payload / 'usr/lib/rpd-gpu-m10', data['apk'], topology)[0]
    composed = policy.select(base, composed, video, data, qualification, data['apk'])[0]
    snapshot = topology.snapshot(libfdt.Fdt(composed))
    assert snapshot['/soc@0/gpu@1c00000']['status'] == b'okay\0'
    assert snapshot['/soc@0/sound-card@c051000']['status'] == b'okay\0'
    assert len([p for p in snapshot.values() if p.get('device_type') == b'cpu\0']) == 4
    (result / 'combined-package.dtb').write_bytes(composed)
    write(args.report, {'status': 'PASS', 'scope': 'real full BSP build and packaged software; no boot/device proof',
                        'apks': rows, 'modules': modules, 'exports': export_rows,
                        'kernel_config_sha256': sha(config), 'vmlinux_sha256': sha((kernel / 'vmlinux').read_bytes()),
                        'packaged_helpers_composed_dt_sha256': sha(composed),
                        'strong_imports_resolve': True, 'matching_optional_build_supported': True,
                        'limitations': ['target boot-deploy/systemd/mkinitfs/loader not tested',
                                        'installed stock GStreamer caller remains unpatched',
                                        '1080 crop, Chromium rendering, codec coverage and playback power open']})
    shutil.rmtree(payload)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('inputs')
    p.add_argument('fixture', type=Path); p.add_argument('manifest', type=Path); p.add_argument('report', type=Path)
    p.add_argument('--stage', type=Path)
    p = commands.add_parser('resources')
    p.add_argument('path', type=Path); p.add_argument('report', type=Path)
    p = commands.add_parser('artifacts')
    p.add_argument('fixture', type=Path); p.add_argument('build', type=Path)
    p.add_argument('packages', type=Path); p.add_argument('keys', type=Path); p.add_argument('report', type=Path)
    args = parser.parse_args()
    globals()[args.command](args)
