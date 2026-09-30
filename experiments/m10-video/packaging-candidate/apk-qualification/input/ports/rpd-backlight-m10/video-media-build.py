#!/usr/bin/env python3
"""Stage a pinned minimal framework; optionally build real exports against /kernel."""
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


def normalize_config(data):
    return b''.join(line for line in data.splitlines(keepends=True)
                    if line != b'CONFIG_CC_CAN_LINK=y\n')


def kernel_inputs(kernel):
    return {name: sha((kernel / name).read_bytes())
            for name in ('.config', 'Module.symvers')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sources', type=Path,
                        help='isolated source root using selected-sources.json staged_path layout')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    assert args.jobs > 0
    kernel, output = args.kernel.resolve(), args.output.resolve()
    assert kernel.is_dir() and not output.exists(), 'use existing kernel and fresh isolated output'
    assert kernel not in output.parents and output != kernel, 'output must be outside shared kernel'
    manifest = json.loads(Path(__file__).with_name('video-media-sources.json').read_text())
    config = (kernel / '.config').read_bytes()
    assert sha(normalize_config(config)) == manifest['normalized_config_sha256'], 'kernel config mismatch'
    assert b'# CONFIG_MODVERSIONS is not set\n' in config, 'MODVERSIONS differs from pinned experiment'
    for name, value in manifest['config'].items():
        assert (name + '=' + value + '\n').encode() in config, name
    assert (kernel / 'Module.symvers').stat().st_size > 0, 'genuine base kernel exports required'
    before = kernel_inputs(kernel)
    source_root = args.sources.resolve() if args.sources else kernel
    assert source_root.is_dir(), 'source root must exist'
    # Verify every selected source before creating or compiling output.
    sources = {}
    for row in manifest['files']:
        source = source_root / (row['staged_path'] if args.sources else row['path'])
        data = source.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert len(data) == row['bytes'] and blob == row['git_blob_sha1'], row['path']
        sources[row['staged_path']] = source
    output.mkdir(parents=True)
    copied = {}
    for row in manifest['files']:
        destination = output / row['staged_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sources[row['staged_path']], destination)
        copied[row['staged_path']] = sha(destination.read_bytes())
    for row in manifest['files']:
        path = output / row['staged_path']
        if path.suffix in ('.c', '.h'):
            for include in re.findall(r'^#include "([^"]+)"', path.read_text(), re.M):
                assert (path.parent / include).is_file(), (path, include)
    lines = ['# Generated external Kbuild; upstream sources and module names retained.',
             'ccflags-y += -I$(srctree)/drivers/media/dvb-frontends',
             'ccflags-y += -I$(srctree)/drivers/media/tuners', '']
    for name, files in manifest['modules'].items():
        lines += ['obj-m += ' + name + '.o',
                  name + '-y := ' + ' '.join(str(Path(file).with_suffix('.o')) for file in files), '']
    (output / 'Kbuild').write_text('\n'.join(lines))
    copied['Kbuild'] = sha((output / 'Kbuild').read_bytes())
    report = {'scope': 'Isolated standard framework source/build; no installation',
              'kernelrelease': manifest['kernelrelease'], 'modversions': False,
              'source_bytes': manifest['source_bytes'], 'c_objects': manifest['c_objects'],
              'source_root': str(source_root),
              'modules_requested': list(manifest['modules']), 'source_hashes': copied,
              'kernel_inputs_before': before, 'built': False}
    report_path = output / 'framework-validation.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    shutil.copyfile(Path(__file__).with_name('video-media-sources.json'), output / 'selected-sources.json')
    print(json.dumps({'output': str(output), 'source_bytes': manifest['source_bytes'],
                      'c_objects': manifest['c_objects'], 'modules': report['modules_requested']}, indent=2), flush=True)
    if not args.build:
        return
    assert not os.environ.get('KBUILD_MODPOST_WARN'), 'modpost warnings must not replace errors'
    assert not os.environ.get('KBUILD_MODPOST_NOFINAL'), 'final modpost checks required'
    release = subprocess.check_output(['make', '-s', '-C', str(kernel), 'LLVM=1', 'kernelrelease'], text=True).strip()
    assert release == manifest['kernelrelease'], release
    try:
        subprocess.run(['make', '-C', str(kernel), 'LLVM=1', '-j' + str(args.jobs),
                        'M=' + str(output), 'modules'], check=True)
    finally:
        assert kernel_inputs(kernel) == before, 'shared .config/Module.symvers changed'
    symbols = output / 'Module.symvers'
    entries = [line.split() for line in symbols.read_text().splitlines() if line.strip()]
    generated_exports = {row[1] for row in entries}
    # These are the observed original Venus modpost failures, not invented rows.
    required = {'v4l2_m2m_ctx_release', 'v4l2_fh_del', 'vb2_plane_cookie', 'vb2_dma_contig_memops'}
    assert required <= generated_exports, sorted(required - generated_exports)
    exports = generated_exports | {line.split()[1] for line in (kernel / 'Module.symvers').read_text().splitlines() if line.strip()}
    modules = []
    magics = set()
    for name in manifest['modules']:
        ko = output / (name + '.ko')
        assert ko.stat().st_size > 0, name
        imports = {words[-1] for line in subprocess.check_output(['llvm-nm', '-u', str(ko)], text=True).splitlines()
                   if (words := line.split()) and words[0] == 'U'}
        assert not imports - exports, (name, sorted(imports - exports))
        def info(field):
            return subprocess.check_output(['modinfo', '-F', field, str(ko)], text=True).strip()
        magic = info('vermagic')
        assert magic.split()[0] == release, (name, magic)
        magics.add(magic)
        modules.append({'file': name + '.ko', 'bytes': ko.stat().st_size,
                        'sha256': sha(ko.read_bytes()), 'vermagic': magic,
                        'depends': info('depends'), 'strong_imports_resolved': len(imports)})
    assert len(magics) == 1, 'inconsistent framework ABI metadata'
    report.update({'built': True, 'kernel_inputs_unchanged': True,
                   'genuine_modpost_exports': len(generated_exports),
                   'module_symvers_sha256': sha(symbols.read_bytes()),
                   'modules': modules, 'module_bytes': sum(row['bytes'] for row in modules)})
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
