#!/usr/bin/env python3
"""Synthetic evidence fixtures based on the supplied offline reservation-only DTB."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import libfdt

script = Path(__file__).with_name('verify-allocation.py')
spec = importlib.util.spec_from_file_location('verify_allocation', script)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
blob = Path(sys.argv[1]).read_bytes()
fdt, pools = probe.expected_pools(blob)
tree = probe.reserve.snapshot(fdt)


def merged(rows):
    result = []
    for row in sorted(rows, key=lambda row: row['start']):
        if result and row['start'] <= result[-1]['end'] + 1:
            result[-1]['end'] = max(result[-1]['end'], row['end'])
        else:
            result.append({'start': row['start'], 'end': row['end']})
    return result


# Allocate only fictional fixture addresses from the DT's requested ranges.
# These are parser tests, never an estimate or prediction of live placement.
rows = [{'name': name, 'start': pool['start'], 'end': pool['start'] + pool['size'] - 1,
         'nomap': pool['nomap'], 'reusable': pool['reusable']}
        for name, pool in pools.items() if pool['start'] is not None]
for name, pool in pools.items():
    if pool['start'] is not None:
        continue
    props = tree['/reserved-memory/' + name]
    start, length = struct.unpack('>QQ', props['alloc-ranges'])
    alignment = struct.unpack('>Q', props['alignment'])[0]
    start = (start + alignment - 1) // alignment * alignment
    while True:
        trial = {'start': start, 'end': start + pool['size'] - 1}
        blockers = [row for row in rows if probe.intersects(trial, row)]
        if not blockers:
            break
        start = (max(row['end'] for row in blockers) + alignment) // alignment * alignment
    assert trial['end'] < struct.unpack('>QQ', props['alloc-ranges'])[0] + length
    rows.append(dict(trial, name=name, nomap=pool['nomap'], reusable=pool['reusable']))
venus = next(row for row in rows if row['name'] == 'venus')


def log_line(row):
    return '[    0.001000] OF: reserved mem: 0x%016x..0x%016x (%d KiB) %s %s %s\n' % (
        row['start'], row['end'], (row['end'] - row['start'] + 1) // 1024,
        'nomap' if row['nomap'] else 'map', 'reusable' if row['reusable'] else 'non-reusable', row['name'])


def block_lines(rows, flag):
    return ''.join('%4d: 0x%016x..0x%016x    x %s\n' % (i, row['start'], row['end'], flag)
                   for i, row in enumerate(rows))


nomap = merged([row for row in rows if row['nomap']])
reserved = merged(rows)
ram_start = min(row['start'] for row in rows) & ~0xfffffff
ram_end = (max(row['end'] for row in rows) + 0x10000000) // 0x10000000 * 0x10000000 - 1
fixture = {'boot_log': '[    0.000000] Linux version ' + probe.KERNEL + ' (SYNTHETIC FIXTURE)\n'
                      + ''.join(log_line(row) for row in rows),
           'memory': block_lines(nomap, 'NOMAP'), 'reserved': block_lines(reserved, 'RSV_KERN'),
           'iomem': '%08x-%08x : System RAM\n' % (ram_start, ram_end) +
                    ''.join('  %08x-%08x : reserved\n' % (row['start'], row['end']) for row in reserved)}
assert probe.validate(blob, **fixture)['status'] == 'verified'
# Merged adjacent named reservations and iomem parent/child nesting must pass.
assert any(row['start'] < venus['start'] and row['end'] >= venus['end'] for row in nomap)
results = []


def rejected(label, expected, data=None, dtb=None, enabled_codec=False):
    try:
        probe.validate(blob if dtb is None else dtb, **(fixture if data is None else data),
                       enabled_codec=enabled_codec)
    except (probe.EvidenceError, AssertionError) as exc:
        assert expected in str(exc), (label, expected, str(exc))
        results.append({'fixture': label, 'reason': str(exc)})
        return
    raise AssertionError('unsafe fixture accepted: ' + label)


def edited_venus(**changes):
    changed = dict(venus, **changes)
    data = dict(fixture)
    data['boot_log'] = data['boot_log'].replace(log_line(venus), log_line(changed))
    return data


rejected('missing early boot marker', 'early Linux version marker', dict(fixture, boot_log=''.join(log_line(row) for row in rows)))
rejected('wrong kernel', 'matching early Linux version', dict(fixture, boot_log=fixture['boot_log'].replace(probe.KERNEL, '7.1.4-msm89x7')))
rejected('duplicate Venus', 'duplicate named', dict(fixture, boot_log=fixture['boot_log'] + log_line(venus)))
rejected('missing Venus', 'named Venus allocation missing', dict(fixture, boot_log=fixture['boot_log'].replace(log_line(venus), '')))
rejected('wrong size', 'not exactly 4 MiB', edited_venus(end=venus['start'] + 0x300000 - 1))
rejected('below window', 'outside allowed window', edited_venus(start=0x86400000, end=0x867fffff))
rejected('crosses upper window', 'outside allowed window', edited_venus(start=0x8e600000, end=0x8e9fffff))
rejected('misaligned', 'not 1 MiB aligned', edited_venus(start=venus['start'] + 1, end=venus['end'] + 1))
rejected('mapped pool', 'nomap and non-reusable', edited_venus(nomap=False))
rejected('reusable pool', 'nomap and non-reusable', edited_venus(reusable=True))
peer = dict(venus, name='another-owner', end=venus['start'] + 0xfff)
rejected('overlapping named peer', 'overlaps named reservation', dict(fixture, boot_log=fixture['boot_log'] + log_line(peer)))
missing_peer = next(row for row in rows if row['name'] != 'venus')
rejected('truncated peer evidence', 'enabled DT reservation missing', dict(fixture, boot_log=fixture['boot_log'].replace(log_line(missing_peer), '')))
rejected('reserved-memory allocation failure', 'reserved-memory error', dict(fixture, boot_log=fixture['boot_log'] + "OF: reserved mem: failed to allocate memory for node 'venus': size 4 MiB\n"))
rejected('kernel overlap report', 'reserved-memory error', dict(fixture, boot_log=fixture['boot_log'] + 'OF: reserved mem: OVERLAP DETECTED!\n'))
rejected('NOMAP not shown', 'NOMAP coverage', dict(fixture, memory=fixture['memory'].replace('NOMAP', 'NONE')))
gap = [dict(row, end=venus['start'] - 1) if probe.intersects(row, venus) else row for row in reserved]
rejected('reserved coverage gap', 'reserved coverage', dict(fixture, reserved=block_lines(gap, 'RSV_KERN')))
rejected('empty iomem', 'iomem view unavailable/empty', dict(fixture, iomem=''))
rejected('redacted iomem', 'iomem addresses unavailable/redacted', dict(fixture, iomem='00000000-00000000 : System RAM\n'))
rejected('malformed memblock', 'malformed/unavailable', dict(fixture, memory='cat: permission denied\n'))
rejected('redacted memblock', 'addresses unavailable/redacted', dict(fixture, memory='0: 0x00000000..0x00000000 x NOMAP\n'))
rejected('other iomem owner', 'iomem owner intersects Venus', dict(fixture, iomem=fixture['iomem'] + '%08x-%08x : Kernel code\n' % (venus['start'], venus['end'])))
bad_map = bytearray(blob)
header = struct.unpack_from('>10I', blob)
bad_map[header[4]:header[4]] = struct.pack('>QQ', venus['start'], 0x1000)
for offset, old in ((4, header[1]), (8, header[2]), (12, header[3])):
    struct.pack_into('>I', bad_map, offset, old + 16)
rejected('FDT reservation overlap', 'overlaps FDT memreserve', dtb=bytes(bad_map))
bad_dt = libfdt.Fdt(blob)
bad_dt.resize(bad_dt.totalsize() + 256)
bad_dt.setprop(bad_dt.path_offset(probe.reserve.MEMORY), 'reg', struct.pack('>QQ', venus['start'], 0x400000))
bad_dt.pack()
rejected('fixed pool reg', 'dynamically allocated', dtb=bytes(bad_dt.as_bytearray()))
enabled_dt = libfdt.Fdt(blob)
enabled_dt.resize(enabled_dt.totalsize() + 256)
enabled_dt.setprop(enabled_dt.path_offset(probe.reserve.CODEC), 'status', b'okay\0')
enabled_dt.pack()
enabled_blob = bytes(enabled_dt.as_bytearray())
rejected('enabled codec without option', 'requires disabled codec', dtb=enabled_blob)
enabled_report = probe.validate(enabled_blob, **fixture, enabled_codec=True)
disabled_report = probe.validate(blob, **fixture)
assert enabled_report['enabled_codec'] is True
assert enabled_report['venus'] == disabled_report['venus'], 'explicit option changed allocation checks'
rejected('disabled codec with enabled option', 'option/status mismatch', enabled_codec=True)
rejected('enabled option cannot bypass allocation geometry', 'not exactly 4 MiB',
         data=edited_venus(end=venus['start'] + 0x300000 - 1),
         dtb=enabled_blob, enabled_codec=True)

# The CLI must preserve missing-view provenance instead of issuing a pass.
with tempfile.TemporaryDirectory(prefix='m10-allocation-fixture-') as temporary:
    root = Path(temporary)
    (root / 'dtb').write_bytes(blob)
    for name, contents in fixture.items():
        (root / name).write_text(contents)
    args = [sys.executable, str(script), '--dtb', str(root / 'dtb'),
            '--boot-log', str(root / 'boot_log'), '--iomem', str(root / 'iomem'),
            '--memory', str(root / 'memory'), '--reserved', str(root / 'missing-reserved')]
    run = subprocess.run(args, capture_output=True, text=True)
    report = json.loads(run.stdout)
    assert run.returncode == 2 and report['status'] == 'unproven'
    assert report['inputs']['reserved']['available'] is False
    results.append({'fixture': 'unavailable reserved file', 'reason': report['error']})
    (root / 'dtb').write_bytes(enabled_blob)
    args[-1] = str(root / 'reserved')
    without_option = subprocess.run(args, capture_output=True, text=True)
    assert without_option.returncode == 2
    assert json.loads(without_option.stdout)['status'] == 'unproven'
    with_option = subprocess.run(args + ['--enabled-codec'], capture_output=True, text=True)
    assert with_option.returncode == 0
    cli_report = json.loads(with_option.stdout)
    assert cli_report['status'] == 'verified' and cli_report['enabled_codec'] is True
print(json.dumps({'status': 'PASS', 'evidence_kind': 'synthetic parser fixtures; no live allocation proof',
                  'positive': 'named allocation, merged NOMAP/reserved coverage, nested iomem; enabled DT accepted only with explicit API/CLI option',
                  'negative_fixtures_rejected': len(results), 'results': results}, indent=2))
