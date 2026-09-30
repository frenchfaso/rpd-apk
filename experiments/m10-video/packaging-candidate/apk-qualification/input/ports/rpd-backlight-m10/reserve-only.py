#!/usr/bin/env python3
"""Compose/validate a reservation-only DTB copy. Never write to boot or sysfs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import libfdt

if not __debug__:
    raise RuntimeError('DT safety checks require Python without -O/PYTHONOPTIMIZE')

MEMORY = '/reserved-memory/venus'
CODEC = '/soc@0/venus@1d00000'
ALLOWED = {(MEMORY, 'status'), (CODEC, 'status')}


def snapshot(fdt):
    result = {}
    def visit(offset, path):
        assert path not in result, ('duplicate node path', path)
        props = {}
        prop = fdt.first_property_offset(offset, quiet=(libfdt.NOTFOUND,))
        while prop >= 0:
            value = fdt.get_property_by_offset(prop)
            assert value.name not in props, ('duplicate property', path, value.name)
            props[value.name] = bytes(value)
            prop = fdt.next_property_offset(prop, quiet=(libfdt.NOTFOUND,))
        result[path] = props
        child = fdt.first_subnode(offset, quiet=(libfdt.NOTFOUND,))
        while child >= 0:
            visit(child, path.rstrip('/') + '/' + fdt.get_name(child))
            child = fdt.next_subnode(child, quiet=(libfdt.NOTFOUND,))
    visit(0, '/')
    return result


def check_layout(tree, codec_compatible=b'qcom,msm8937-venus\0'):
    assert tree['/']['compatible'] == b'lenovo,tbx505x\0qcom,sdm429\0', 'unexpected board'
    memory = tree[MEMORY]
    assert 'reg' not in memory, 'reservation must remain dynamically allocated'
    assert memory['size'] == struct.pack('>Q', 0x400000), 'unexpected pool size'
    assert memory['alignment'] == struct.pack('>Q', 0x100000), 'unexpected alignment'
    assert memory['alloc-ranges'] == struct.pack('>QQ', 0x86800000, 0x8000000), 'unexpected window'
    assert memory['no-map'] == b'', 'missing no-map reservation'
    assert tree[CODEC]['compatible'] == codec_compatible, 'unexpected codec compatible'
    assert tree[CODEC]['memory-region'] == memory['phandle'], 'wrong firmware pool phandle'


def memreserve(fdt):
    return [fdt.get_mem_rsv(i) for i in range(fdt.num_mem_rsv())]


def validate(original, candidate):
    old_fdt, new_fdt = libfdt.Fdt(original), libfdt.Fdt(candidate)
    old, new = snapshot(old_fdt), snapshot(new_fdt)
    check_layout(old)
    check_layout(new)
    # Layout offsets/sizes may change; version and the boot CPU identity may not.
    old_header = struct.unpack_from('>10I', original)
    new_header = struct.unpack_from('>10I', candidate)
    assert old_header[5:8] == new_header[5:8], 'FDT version/boot CPU semantics changed'
    assert set(old) == set(new), 'node inventory changed'
    assert memreserve(old_fdt) == memreserve(new_fdt), 'FDT memreserve map changed'
    assert new[MEMORY]['status'] == b'okay\0', 'pool is not enabled'
    assert new[CODEC]['status'] == b'disabled\0', 'codec must remain disabled'
    changes = []
    for path in old:
        for name in set(old[path]) | set(new[path]):
            before, after = old[path].get(name), new[path].get(name)
            if before != after:
                assert (path, name) in ALLOWED, ('unrelated property changed', path, name)
                changes.append({'path': path, 'property': name,
                                'before': None if before is None else before.rstrip(b'\0').decode(),
                                'after': after.rstrip(b'\0').decode()})
    return {'scope': 'Offline DTB comparison only; no deployed reservation',
            'input_sha256': hashlib.sha256(original).hexdigest(),
            'output_sha256': hashlib.sha256(candidate).hexdigest(),
            'changes': sorted(changes, key=lambda x: x['path']),
            'memreserve_unchanged': True, 'header_semantics_unchanged': True,
            'unrelated_properties_unchanged': True,
            'allocation': {'bytes': 0x400000, 'alignment': 0x100000,
                           'window_start': 0x86800000, 'window_end': 0x8e800000,
                           'dynamic': True}, 'codec': 'disabled'}


def compose(blob):
    fdt = libfdt.Fdt(blob)
    tree = snapshot(fdt)
    check_layout(tree)
    assert tree[MEMORY].get('status') in (b'disabled\0', b'okay\0'), 'unexpected pool state'
    assert tree[CODEC].get('status') in (None, b'okay\0', b'disabled\0'), 'unexpected codec state'
    fdt.resize(fdt.totalsize() + 256)
    fdt.setprop_str(fdt.path_offset(MEMORY), 'status', 'okay')
    fdt.setprop_str(fdt.path_offset(CODEC), 'status', 'disabled')
    fdt.pack()
    candidate = bytes(fdt.as_bytearray())
    return candidate, validate(blob, candidate)


def offline_output(path, source):
    path = path.resolve()
    assert path != source.resolve(), 'refusing to overwrite the input DTB'
    assert not any(path == root or root in path.parents
                   for root in (Path('/boot'), Path('/sys'), Path('/proc'), Path('/dev'))), 'offline output path required'
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='current composed DTB copied to an offline file')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path, help='write a reservation-only offline copy')
    action.add_argument('--validate', type=Path, help='validate an existing candidate copy')
    args = parser.parse_args()
    original = args.input.read_bytes()
    if args.output:
        output = offline_output(args.output, args.input)
        candidate, report = compose(original)
        output.write_bytes(candidate)
    else:
        report = validate(original, args.validate.read_bytes())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
