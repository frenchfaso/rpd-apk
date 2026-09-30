#!/usr/bin/env python3
"""Compose/validate only the reviewed experimental Venus topology in an offline DTB."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import libfdt

spec = importlib.util.spec_from_file_location('reserve_only', Path(__file__).with_name('reserve-only.py'))
reserve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reserve)
MEMORY, CODEC = reserve.MEMORY, reserve.CODEC
TABLE = CODEC + '/opp-table'
OLD_COMPAT = b'qcom,msm8937-venus\0'
NEW_COMPAT = b'qcom,sdm429-venus\0'
RATES = (166150000, 240000000, 308571428, 320000000, 360000000)
LEVELS = (128, 192, 256, 320, 384)
OLD_LEVELS = (48, 64, 256, 320, 384)
ALLOWED = {(MEMORY, 'status'), (CODEC, 'compatible'), (CODEC, 'status'),
           (CODEC, 'power-domains'), (CODEC, 'power-domain-names'),
           (CODEC, 'operating-points-v2'), (TABLE, 'phandle'),
           (TABLE + '/opp-166150000', 'required-opps'),
           (TABLE + '/opp-240000000', 'required-opps')}


def cells(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def value(data):
    assert len(data) == 4, 'expected a single cell'
    return struct.unpack('>I', data)[0]


def phandles(tree):
    result = {}
    for path, props in tree.items():
        phandle = props.get('phandle', props.get('linux,phandle'))
        if phandle is not None:
            number = value(phandle)
            assert 0 < number < 0xffffffff, ('invalid phandle', path)
            assert number not in result, ('duplicate phandle', path)
            if 'linux,phandle' in props:
                assert props['linux,phandle'] == phandle, ('phandle aliases differ', path)
            result[number] = path
    return result


def unique_compatible(tree, compatible):
    paths = [path for path, props in tree.items() if props.get('compatible') == compatible]
    assert len(paths) == 1, ('expected one provider', compatible, paths)
    return paths[0]


def layout(tree):
    compat = tree[CODEC]['compatible']
    assert compat in (OLD_COMPAT, NEW_COMPAT), 'unexpected codec compatible'
    reserve.check_layout(tree, codec_compatible=compat)
    assert tree[MEMORY].get('status') in (b'disabled\0', b'okay\0'), 'unexpected pool state'
    assert tree[CODEC].get('status') in (None, b'disabled\0', b'okay\0'), 'unexpected codec state'
    handles = phandles(tree)
    gcc = unique_compatible(tree, b'qcom,gcc-sdm439\0')
    rpm = unique_compatible(tree, b'qcom,sdm439-rpmpd\0')
    for provider in (gcc, rpm):
        assert tree[provider]['#power-domain-cells'] == cells(1), provider
    gcc_handle, rpm_handle = value(tree[gcc]['phandle']), value(tree[rpm]['phandle'])
    table = tree[TABLE]
    assert table['compatible'] == b'operating-points-v2\0', 'unexpected Venus OPP table'
    children = {path for path in tree if path.startswith(TABLE + '/')}
    assert children == {TABLE + '/opp-' + str(rate) for rate in RATES}, 'unexpected Venus OPP inventory'
    rpm_table_handle = value(tree[rpm]['operating-points-v2'])
    rpm_table = handles[rpm_table_handle]
    assert rpm_table.startswith(rpm + '/') and tree[rpm_table]['compatible'] == b'operating-points-v2\0'
    rpm_opps = {}
    for path, props in tree.items():
        if path.startswith(rpm_table + '/') and 'opp-level' in props and 'phandle' in props:
            level = value(props['opp-level'])
            assert level not in rpm_opps, 'ambiguous RPM level'
            rpm_opps[level] = value(props['phandle'])
    assert set(OLD_LEVELS + LEVELS) <= set(rpm_opps), 'required existing RPM OPP missing'
    expected_levels = OLD_LEVELS if compat == OLD_COMPAT else LEVELS
    for rate, level in zip(RATES, expected_levels):
        props = tree[TABLE + '/opp-' + str(rate)]
        assert props['opp-hz'] == struct.pack('>Q', rate), ('unexpected rate', rate)
        assert props['required-opps'] == cells(rpm_opps[level]), ('unexpected RPM linkage', rate)
    domains = cells(gcc_handle, 5, gcc_handle, 4)  # VENUS_GDSC, VENUS_CORE0_GDSC
    if compat == NEW_COMPAT:
        domains += cells(rpm_handle, 1)  # SDM439_VDDCX
    assert tree[CODEC]['power-domains'] == domains, 'unexpected codec power domains'
    names = b'venus\0vcodec0\0' + (b'cx\0' if compat == NEW_COMPAT else b'')
    assert tree[CODEC]['power-domain-names'] == names, 'unexpected codec domain names'
    table_handle = table.get('phandle')
    if compat == NEW_COMPAT:
        assert table_handle is not None and tree[CODEC]['operating-points-v2'] == table_handle, 'missing Venus OPP reference'
    elif 'operating-points-v2' in tree[CODEC]:
        assert table_handle is not None and tree[CODEC]['operating-points-v2'] == table_handle
    return {'gcc': gcc_handle, 'rpm': rpm_handle, 'rpm_opps': rpm_opps,
            'table': None if table_handle is None else value(table_handle), 'handles': handles}


def validate(original, candidate, enable=False):
    old_fdt, new_fdt = libfdt.Fdt(original), libfdt.Fdt(candidate)
    old, new = reserve.snapshot(old_fdt), reserve.snapshot(new_fdt)
    old_layout, new_layout = layout(old), layout(new)
    assert new[CODEC]['compatible'] == NEW_COMPAT, 'candidate compatible missing'
    assert new[MEMORY]['status'] == b'okay\0', 'pool is not enabled'
    assert new[CODEC]['status'] == (b'okay\0' if enable else b'disabled\0'), 'explicit codec enable flag/state mismatch'
    assert set(old) == set(new), 'node inventory changed'
    assert reserve.memreserve(old_fdt) == reserve.memreserve(new_fdt), 'FDT memreserve map changed'
    assert struct.unpack_from('>10I', original)[5:8] == struct.unpack_from('>10I', candidate)[5:8], 'FDT version/boot CPU semantics changed'
    table_handle = old_layout['table']
    if table_handle is None:
        table_handle = max(old_layout['handles']) + 1
        assert table_handle < 0xffffffff, 'no available phandle'
    assert new_layout['table'] == table_handle, 'unexpected allocated OPP table phandle'
    changes = []
    for path in old:
        for name in set(old[path]) | set(new[path]):
            before, after = old[path].get(name), new[path].get(name)
            if before != after:
                assert (path, name) in ALLOWED, ('unrelated property changed', path, name)
                changes.append({'path': path, 'property': name,
                                'before_hex': None if before is None else before.hex(),
                                'after_hex': None if after is None else after.hex()})
    return {'scope': 'Offline experimental DTB only; unpublished compatible, no deployment',
            'input_sha256': hashlib.sha256(original).hexdigest(),
            'output_sha256': hashlib.sha256(candidate).hexdigest(),
            'changes': sorted(changes, key=lambda row: (row['path'], row['property'])),
            'memreserve_unchanged': True, 'header_semantics_unchanged': True,
            'unrelated_properties_unchanged': True, 'codec': 'enabled' if enable else 'disabled',
            'power_domains': ['venus', 'vcodec0', 'cx'], 'cx_domain_index': 1,
            'opp_table_phandle': table_handle, 'frequencies_hz': list(RATES),
            'required_rpm_levels': list(LEVELS)}


def compose(blob, enable=False):
    fdt = libfdt.Fdt(blob)
    tree = reserve.snapshot(fdt)
    resources = layout(tree)
    table_handle = resources['table']
    if table_handle is None:
        table_handle = max(resources['handles']) + 1
        assert table_handle < 0xffffffff, 'no available phandle'
    fdt.resize(fdt.totalsize() + 1024)
    def setprop(path, name, data):
        fdt.setprop(fdt.path_offset(path), name, data)
    setprop(MEMORY, 'status', b'okay\0')
    setprop(CODEC, 'compatible', NEW_COMPAT)
    setprop(CODEC, 'power-domains', cells(resources['gcc'], 5, resources['gcc'], 4, resources['rpm'], 1))
    setprop(CODEC, 'power-domain-names', b'venus\0vcodec0\0cx\0')
    setprop(TABLE, 'phandle', cells(table_handle))
    setprop(CODEC, 'operating-points-v2', cells(table_handle))
    for rate, level in zip(RATES[:2], LEVELS[:2]):
        setprop(TABLE + '/opp-' + str(rate), 'required-opps', cells(resources['rpm_opps'][level]))
    setprop(CODEC, 'status', b'okay\0' if enable else b'disabled\0')
    fdt.pack()
    candidate = bytes(fdt.as_bytearray())
    return candidate, validate(blob, candidate, enable=enable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='offline copy of current installed or reservation-only DTB')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path)
    action.add_argument('--validate', type=Path)
    parser.add_argument('--enable', action='store_true', help='explicitly compose/validate codec status okay for a later separately authorized trial')
    args = parser.parse_args()
    original = args.input.read_bytes()
    if args.output:
        output = reserve.offline_output(args.output, args.input)
        candidate, report = compose(original, enable=args.enable)
        output.write_bytes(candidate)
    else:
        report = validate(original, args.validate.read_bytes(), enable=args.enable)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
