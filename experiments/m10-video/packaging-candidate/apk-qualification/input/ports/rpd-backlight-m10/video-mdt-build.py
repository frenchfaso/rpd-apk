#!/usr/bin/env python3
"""Stage and optionally compile the unchanged pinned MDT loader outside /kernel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def kernel_inputs(kernel):
    return {name: sha((kernel / name).read_bytes())
            for name in ('.config', 'Module.symvers')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    assert args.jobs > 0
    root = Path(__file__).resolve().parent
    kernel, output = args.kernel.resolve(), args.output.resolve()
    assert kernel.is_dir() and not output.exists(), 'existing kernel and fresh output required'
    assert kernel not in output.parents and output != kernel, 'output must be outside shared kernel'
    manifest = json.loads((root / 'video-mdt-sources.json').read_text())
    config = (kernel / '.config').read_bytes()
    normalized = b''.join(line for line in config.splitlines(keepends=True)
                          if line != b'CONFIG_CC_CAN_LINK=y\n')
    assert sha(normalized) == manifest['normalized_config_sha256'], 'kernel config mismatch'
    assert b'# CONFIG_MODVERSIONS is not set\n' in config, 'MODVERSIONS config mismatch'
    for name, value in manifest['config'].items():
        assert (name + '=' + value + '\n').encode() in config, name
    assert (kernel / 'Module.symvers').stat().st_size > 0, 'genuine base kernel exports required'
    if args.build:
        assert not os.environ.get('KBUILD_MODPOST_WARN'), 'strict modpost errors required'
        assert not os.environ.get('KBUILD_MODPOST_NOFINAL'), 'final modpost required'
    before = kernel_inputs(kernel)
    source_hashes = {}
    for row in manifest['files']:
        data = (kernel / row['path']).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert len(data) == row['bytes'] and blob == row['git_blob_sha1'], row['path']
        assert sha(data) == row['sha256'], row['path']
        if row['staged_path'].endswith('.c'):
            assert not re.findall(r'^#include "([^"]+)"', data.decode(), re.M), 'local headers missing'
        source_hashes[row['staged_path']] = sha(data)
    output.mkdir(parents=True)
    for row in manifest['files']:
        shutil.copyfile(kernel / row['path'], output / row['staged_path'])
    (output / 'Kbuild').write_text('# Unchanged upstream module name and source.\nobj-m += mdt_loader.o\n')
    source_hashes['Kbuild'] = sha((output / 'Kbuild').read_bytes())
    shutil.copyfile(root / 'video-mdt-sources.json', output / 'source-manifest.json')
    report = {'scope': 'Isolated standard MDT loader build metadata; no installation',
              'built': False, 'kernelrelease': manifest['kernelrelease'], 'modversions': False,
              'source_bytes': sum(row['bytes'] for row in manifest['files']),
              'c_objects': 1, 'modules_requested': ['mdt_loader'],
              'source_hashes': source_hashes, 'kernel_inputs_before': before}
    report_path = output / 'mdt-validation.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'source_bytes': report['source_bytes'],
                      'c_objects': 1, 'modules': ['mdt_loader']}, indent=2), flush=True)
    if not args.build:
        return
    release = subprocess.check_output(['make', '-s', '-C', str(kernel), 'LLVM=1', 'kernelrelease'], text=True).strip()
    assert release == manifest['kernelrelease'], release
    try:
        subprocess.run(['make', '-C', str(kernel), 'LLVM=1', '-j' + str(args.jobs),
                        'M=' + str(output), 'modules'], check=True)
    finally:
        assert kernel_inputs(kernel) == before, 'shared .config/Module.symvers changed'
    symbols = output / 'Module.symvers'
    generated_exports = {line.split()[1] for line in symbols.read_text().splitlines() if line.strip()}
    required = {'qcom_mdt_get_size', 'qcom_mdt_load', 'qcom_mdt_load_no_init'}
    assert required <= generated_exports, sorted(required - generated_exports)
    exports = generated_exports | {line.split()[1] for line in (kernel / 'Module.symvers').read_text().splitlines() if line.strip()}
    ko = output / 'mdt_loader.ko'
    assert ko.stat().st_size > 0
    imports = {words[-1] for line in subprocess.check_output(['llvm-nm', '-u', str(ko)], text=True).splitlines()
               if (words := line.split()) and words[0] == 'U'}
    assert not imports - exports, sorted(imports - exports)
    def info(field):
        return subprocess.check_output(['modinfo', '-F', field, str(ko)], text=True).strip()
    magic = info('vermagic')
    assert magic.split()[0] == release, magic
    report.update({'built': True, 'kernel_inputs_unchanged': True,
                   'genuine_modpost_exports': sorted(generated_exports),
                   'module_symvers_sha256': sha(symbols.read_bytes()),
                   'module': {'file': ko.name, 'bytes': ko.stat().st_size,
                              'sha256': sha(ko.read_bytes()), 'vermagic': magic,
                              'depends': info('depends'), 'strong_imports_resolved': len(imports)}})
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
