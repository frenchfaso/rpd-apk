#!/usr/bin/env python3
"""Validate saved read-only evidence of the reservation-only Venus allocation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import libfdt

spec = importlib.util.spec_from_file_location('reserve_only', Path(__file__).with_name('reserve-only.py'))
reserve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reserve)
KERNEL = '7.1.3-msm89x7'
ADDRESS = r'(?:0x)?[0-9a-fA-F]+'
LOG_RANGE = re.compile(r'OF: reserved mem:\s+(' + ADDRESS + r')\.\.(' + ADDRESS +
                       r')\s+\((\d+) KiB\)\s+(nomap|map)\s+(non-reusable|reusable)\s+(\S+)\s*$')
BLOCK_RANGE = re.compile(r'^\s*(\d+):\s+(' + ADDRESS + r')\.\.(' + ADDRESS +
                         r')\s+(?:x|-?\d+)\s+([A-Z_]+)\s*$')
IOMEM_RANGE = re.compile(r'^\s*([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+:\s+(\S.*?)\s*$')


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def interval(start, end, label):
    start, end = int(start, 16), int(end, 16)
    require(0 <= start <= end < 1 << 64, 'invalid physical interval: ' + label)
    return {'start': start, 'end': end, 'name': label}


def intersects(left, right):
    return left['start'] <= right['end'] and right['start'] <= left['end']


def covers(rows, target):
    position = target['start']
    for row in sorted(rows, key=lambda row: row['start']):
        if row['end'] < position:
            continue
        if row['start'] > position:
            return False
        position = row['end'] + 1
        if position > target['end']:
            return True
    return False


def expected_pools(blob, enabled_codec=False):
    fdt = libfdt.Fdt(blob)
    tree = reserve.snapshot(fdt)
    compatible = tree[reserve.CODEC]['compatible']
    require(compatible in (b'qcom,msm8937-venus\0', b'qcom,sdm429-venus\0'), 'unexpected codec compatible')
    reserve.check_layout(tree, codec_compatible=compatible)
    require(tree[reserve.MEMORY]['status'] == b'okay\0', 'composed DT pool is not enabled')
    expected_status = b'okay\0' if enabled_codec else b'disabled\0'
    require(tree[reserve.CODEC]['status'] == expected_status,
            'explicit enabled-codec option/status mismatch' if enabled_codec
            else 'reservation-only evidence requires disabled codec')
    root = tree['/reserved-memory']
    require(root['#address-cells'] == root['#size-cells'] == struct.pack('>I', 2), 'unexpected reservation cells')
    require(root['ranges'] == b'', 'unexpected reservation address translation')
    pools = {}
    for path, props in tree.items():
        if path.rsplit('/', 1)[0] != '/reserved-memory' or props.get('status') not in (None, b'okay\0'):
            continue
        name = path.rsplit('/', 1)[1]
        if 'reg' in props:
            require(len(props['reg']) == 16, 'unsupported multiple/static reservation range: ' + name)
            start, size = struct.unpack('>QQ', props['reg'])
        else:
            require('size' in props and len(props['size']) == 8, 'missing dynamic size: ' + name)
            start, size = None, struct.unpack('>Q', props['size'])[0]
        require(size > 0, 'empty enabled reservation: ' + name)
        pools[name] = {'start': start, 'size': size, 'nomap': 'no-map' in props,
                       'reusable': 'reusable' in props}
    return fdt, pools


def parse_log(text):
    require(text.strip(), 'full boot log unavailable/empty')
    versions = re.findall(r'Linux version (\S+)', text)
    require(versions == [KERNEL], 'full single-boot log with matching early Linux version marker required')
    failures = [line for line in text.splitlines() if 'OF: reserved mem:' in line and
                re.search(r'OVERLAP DETECTED|failed to (?:allocate|reserve)|compatible matching fail|'
                          r'invalid (?:size|alignment)|unsupported node format|not enough space|'
                          r'Failed to allocate', line)]
    require(not failures, 'reserved-memory error: ' + '; '.join(failures))
    rows = []
    for line in text.splitlines():
        match = LOG_RANGE.search(line)
        if match:
            start, end, kib, mapping, reuse, name = match.groups()
            row = interval(start, end, name)
            require((row['end'] - row['start'] + 1) // 1024 == int(kib), 'log size/range mismatch: ' + name)
            row.update({'bytes': row['end'] - row['start'] + 1,
                        'nomap': mapping == 'nomap', 'reusable': reuse == 'reusable'})
            rows.append(row)
    require(rows, 'no exact info-level reserved-memory ranges in full boot log')
    require(len({row['name'] for row in rows}) == len(rows), 'duplicate named reserved-memory range')
    return rows


def parse_memblock(text, view):
    require(text.strip(), view + ' view unavailable/empty')
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = BLOCK_RANGE.fullmatch(line)
        require(match is not None, 'malformed/unavailable ' + view + ' view')
        index, start, end, flag = match.groups()
        row = interval(start, end, view)
        require(int(index) == len(rows), 'incomplete/out-of-order ' + view + ' view')
        row['flag'] = flag
        if rows:
            require(rows[-1]['end'] < row['start'], 'overlapping/out-of-order ' + view + ' ranges')
        rows.append(row)
    require(rows and any(row['start'] or row['end'] for row in rows), view + ' addresses unavailable/redacted')
    return rows


def parse_iomem(text):
    require(text.strip(), 'iomem view unavailable/empty')
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = IOMEM_RANGE.fullmatch(line)
        require(match is not None, 'malformed/unavailable iomem view')
        rows.append(interval(*match.groups()))
    require(rows and any(row['start'] or row['end'] for row in rows), 'iomem addresses unavailable/redacted')
    return rows


def validate(blob, boot_log, iomem, memory, reserved, enabled_codec=False):
    fdt, pools = expected_pools(blob, enabled_codec=enabled_codec)
    rows = parse_log(boot_log)
    named = {row['name']: row for row in rows}
    require('venus' in named, 'named Venus allocation missing')
    venus = named['venus']
    require(venus['bytes'] == 0x400000, 'Venus allocation is not exactly 4 MiB')
    require(venus['nomap'] and not venus['reusable'], 'Venus must be nomap and non-reusable')
    require(venus['start'] % 0x100000 == 0, 'Venus allocation is not 1 MiB aligned')
    require(venus['start'] >= 0x86800000 and venus['end'] + 1 <= 0x8e800000, 'Venus allocation outside allowed window')
    for name, expected in pools.items():
        require(name in named, 'incomplete boot log: enabled DT reservation missing: ' + name)
        actual = named[name]
        require(actual['bytes'] == expected['size'], 'DT/log reservation size differs: ' + name)
        if expected['start'] is not None:
            require(actual['start'] == expected['start'], 'DT/log static reservation address differs: ' + name)
        require(actual['nomap'] == expected['nomap'] and actual['reusable'] == expected['reusable'], 'DT/log reservation flags differ: ' + name)
    for peer in rows:
        if peer['name'] != 'venus':
            require(not intersects(venus, peer), 'Venus overlaps named reservation: ' + peer['name'])
    reservations = reserve.memreserve(fdt)
    for start, size in reservations:
        if size:
            require(start + size <= 1 << 64, 'invalid overflowing FDT memreserve entry')
            require(not intersects(venus, {'start': start, 'end': start + size - 1}), 'Venus overlaps FDT memreserve entry')
    memory_rows = parse_memblock(memory, 'memblock memory')
    reserved_rows = parse_memblock(reserved, 'memblock reserved')
    require(covers([row for row in memory_rows if row['flag'] == 'NOMAP'], venus), 'Venus lacks complete memblock NOMAP coverage')
    require(covers(reserved_rows, venus), 'Venus lacks complete memblock reserved coverage')
    iomem_rows = parse_iomem(iomem)
    # The resource tree nests System RAM and reserved children. Generic labels
    # do not prove ownership; a distinct named owner crossing Venus is a conflict.
    generic = {'System RAM', 'reserved', 'Reserved memory'}
    for row in iomem_rows:
        require(not intersects(venus, row) or row['name'] in generic, 'iomem owner intersects Venus: ' + row['name'])
    return {'status': 'verified', 'scope': 'Saved read-only reservation evidence; no probe/decode proof',
            'kernelrelease': KERNEL, 'dtb_sha256': hashlib.sha256(blob).hexdigest(),
            'format_source_tag': 'v7.1.3-r1',
            'enabled_codec': enabled_codec,
            'venus': {'start': hex(venus['start']), 'end_inclusive': hex(venus['end']),
                      'bytes': venus['bytes'], 'alignment': 0x100000,
                      'nomap': True, 'reusable': False},
            'named_reserved_ranges': len(rows), 'enabled_dt_reservations': len(pools),
            'fdt_memreserve_entries': len(reservations), 'peer_overlaps': False,
            'nomap_coverage': True, 'reserved_coverage': True,
            'iomem_ranges': len(iomem_rows), 'iomem_role': 'supplementary owner conflict check'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', required=True, type=Path)
    parser.add_argument('--boot-log', required=True, type=Path)
    parser.add_argument('--iomem', required=True, type=Path)
    parser.add_argument('--memory', required=True, type=Path)
    parser.add_argument('--reserved', required=True, type=Path)
    parser.add_argument('--enabled-codec', action='store_true',
                        help='explicitly validate codec status okay after the separately enabled candidate boot')
    args = parser.parse_args()
    inputs, data, errors = {}, {}, []
    for name in ('dtb', 'boot_log', 'iomem', 'memory', 'reserved'):
        path = getattr(args, name)
        try:
            contents = path.read_bytes()
            require(bool(contents.strip()), name + ' input unavailable/empty')
            data[name] = contents if name == 'dtb' else contents.decode('utf-8')
            inputs[name] = {'path': str(path), 'bytes': len(contents),
                            'sha256': hashlib.sha256(contents).hexdigest(), 'available': True}
        except (OSError, UnicodeError, EvidenceError) as exc:
            inputs[name] = {'path': str(path), 'available': False, 'error': str(exc)}
            errors.append(str(exc))
    try:
        require(not errors, '; '.join(errors))
        report = validate(data['dtb'], data['boot_log'], data['iomem'], data['memory'], data['reserved'],
                          enabled_codec=args.enabled_codec)
    except (EvidenceError, AssertionError, KeyError, libfdt.FdtException) as exc:
        report = {'status': 'unproven', 'scope': 'Saved read-only evidence; no hardware operations',
                  'error': str(exc)}
    report['inputs'] = inputs
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'verified' else 2


if __name__ == '__main__':
    sys.exit(main())
