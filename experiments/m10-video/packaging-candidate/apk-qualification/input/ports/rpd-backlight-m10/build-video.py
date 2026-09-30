#!/usr/bin/env python3
"""Reuse the already built kernel; isolate real media/MDT exports and patched Venus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import importlib.util

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('video_dtb', HERE / 'video-dtb.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def config_sha(data):
    return policy.sha(b''.join(line for line in data.splitlines(keepends=True)
                              if line != b'CONFIG_CC_CAN_LINK=y\n'))


def eligible(qualification, apk, release, config, base):
    return (apk == qualification['apk'] and release == qualification['release']
            and config_sha(config) == qualification['normalized_config_sha256']
            and policy.identity(base) == qualification['official_dtb_identity_sha256'])


def prepare_venus(kernel, output, qualification):
    tree = Path('drivers/media/platform/qcom/venus')
    module = output / tree
    module.mkdir(parents=True)
    manifest = json.loads((HERE / 'video-venus-sources.json').read_text())
    for row in manifest['files']:
        data = (kernel / tree / row['file']).read_bytes()
        assert policy.sha(data) == row['sha256'] and len(data) == row['bytes'], row['file']
        (module / row['file']).write_bytes(data)
    board = Path('arch/arm64/boot/dts/qcom/sdm429-lenovo-tbx505x.dts')
    data = (kernel / board).read_bytes()
    assert policy.sha(data) == qualification['board_source_sha256'], 'board source changed'
    (output / board).parent.mkdir(parents=True)
    (output / board).write_bytes(data)
    # Binding is carried in this private source tree for review/schema validation;
    # these patches never enter the shared official kernel source/build directory.
    for name, digest in qualification['patches'].items():
        patch = HERE / name
        assert policy.sha(patch.read_bytes()) == digest, name
        result = subprocess.run(['patch', '-p1', '-F', '0', '-i', str(patch)], cwd=output,
                                capture_output=True, text=True, check=True)
        assert 'offset' not in result.stdout and 'fuzz' not in result.stdout, result.stdout
    text = (module / 'Makefile').read_text()
    assert text.count('obj-$(CONFIG_VIDEO_QCOM_VENUS)') == 3
    # No encoder goal; the private SDM429 resource also creates no encoder child.
    lines = [line for line in text.splitlines() if not line.startswith('venus-enc')
             and '+= venus-enc.o' not in line]
    (module / 'Kbuild').write_text('\n'.join(lines).replace('obj-$(CONFIG_VIDEO_QCOM_VENUS)', 'obj-m') + '\n')
    assert 'venus-enc' not in (module / 'Kbuild').read_text()
    assert policy.sha((module / 'core.c').read_bytes()) == qualification['prepared_venus_core_sha256'], 'private core source differs'
    assert policy.sha((module / 'vdec.c').read_bytes()) == qualification['prepared_venus_vdec_sha256'], 'private decoder source differs'
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--apk', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--stage-only', action='store_true', help='source preparation fixture; no compilation')
    args = parser.parse_args()
    kernel, output = args.kernel.resolve(), args.output.resolve()
    assert not output.exists() and kernel != output and kernel not in output.parents
    qualification = json.loads((HERE / 'video-qualification.json').read_text())
    config, base = (kernel / '.config').read_bytes(), args.base.read_bytes()
    metadata = {'supported': False, 'apk': args.apk, 'release': args.release,
                'qualification_sha256': policy.sha((HERE / 'video-qualification.json').read_bytes())}
    output.mkdir(parents=True)
    report_path = output / 'kernel.json'
    report_path.write_text(json.dumps(metadata, indent=2) + '\n')
    if not eligible(qualification, args.apk, args.release, config, base):
        print('Optional video unqualified for current kernel/config/official DT; skipped')
        return
    assert b'CONFIG_VIDEO_QCOM_VENUS=m\n' in config
    assert not os.environ.get('KBUILD_MODPOST_WARN') and not os.environ.get('KBUILD_MODPOST_NOFINAL')
    before = {name: policy.sha((kernel / name).read_bytes()) for name in ('.config', 'Module.symvers')}
    venus = prepare_venus(kernel, output / 'venus-source', qualification)
    try:
        for helper, directory in (('video-media-build.py', 'media'), ('video-mdt-build.py', 'mdt')):
            command = ['python3', str(HERE / helper), str(kernel), str(output / directory)]
            if not args.stage_only:
                command.append('--build')
            subprocess.run(command, check=True)
        if args.stage_only:
            print('Prepared private source only; supported remains false until strict build succeeds')
            return
        assert subprocess.check_output(['make', '-s', '-C', str(kernel), 'LLVM=1', 'kernelrelease'], text=True).strip() == args.release
        symvers = [output / 'media/Module.symvers', output / 'mdt/Module.symvers']
        subprocess.run(['make', '-C', str(kernel), 'LLVM=1', '-j2', 'M=' + str(venus),
                        'KBUILD_EXTRA_SYMBOLS=' + ' '.join(map(str, symvers)), 'modules'], check=True)
        exports = {line.split()[1] for path in [kernel / 'Module.symvers', *symvers, venus / 'Module.symvers']
                   for line in path.read_text().splitlines() if line.strip()}
        modules = list((output / 'media').glob('*.ko')) + list((output / 'mdt').glob('*.ko'))
        modules += [venus / 'venus-core.ko', venus / 'venus-dec.ko']
        assert not (venus / 'venus-enc.ko').exists()
        rows, magics = [], set()
        for module in modules:
            imports = {words[-1] for line in subprocess.check_output(['llvm-nm', '-u', str(module)], text=True).splitlines()
                       if (words := line.split()) and words[0] == 'U'}
            assert not imports - exports, (module.name, sorted(imports - exports))
            info = lambda field: subprocess.check_output(['modinfo', '-F', field, str(module)], text=True).strip()
            magic = info('vermagic')
            assert magic.split()[0] == args.release, (module.name, magic)
            magics.add(magic)
            destination = output / module.name
            shutil.copyfile(module, destination)
            rows.append({'file': module.name, 'sha256': policy.sha(destination.read_bytes()),
                         'vermagic': magic, 'depends': info('depends'), 'srcversion': info('srcversion')})
        assert len(magics) == 1 and len(rows) == 10
        shutil.copyfile(args.base, output / 'base.dtb')
        metadata.update({'supported': True, 'modules': rows,
                         'base_identity_sha256': policy.identity(base),
                         'normalized_config_sha256': config_sha(config),
                         'source_files': {str(path.relative_to(output)): policy.sha(path.read_bytes())
                                          for path in (output / 'venus-source').rglob('*')
                                          if path.is_file() and path.suffix in ('.c', '.h', '.yaml', '.dts')},
                         'private_decoder_only': True})
        report_path.write_text(json.dumps(metadata, indent=2) + '\n')
    finally:
        assert before == {name: policy.sha((kernel / name).read_bytes()) for name in before}, 'shared kernel inputs changed'


if __name__ == '__main__':
    main()
