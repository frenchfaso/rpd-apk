#!/usr/bin/python3
"""Derive the M10 DTB from the installed kernel, preserving unrelated hardware."""
import argparse
import os
from pathlib import Path
import struct
import sys
import tempfile
import libfdt

KEEP = {0x100, 0x101, 0x102, 0x103}
REMOVE = {0, 1, 2, 3}

class Unsupported(ValueError):
    pass

def cells(data):
    if len(data) % 4:
        raise Unsupported('unaligned cell data')
    return struct.unpack('>' + 'I' * (len(data) // 4), data)

def snapshot(fdt):
    result = {}
    def visit(offset, path):
        props = {}
        prop = fdt.first_property_offset(offset, quiet=(libfdt.NOTFOUND,))
        while prop >= 0:
            value = fdt.get_property_by_offset(prop)
            props[value.name] = bytes(value)
            prop = fdt.next_property_offset(prop, quiet=(libfdt.NOTFOUND,))
        result[path] = props
        child = fdt.first_subnode(offset, quiet=(libfdt.NOTFOUND,))
        while child >= 0:
            visit(child, path.rstrip('/') + '/' + fdt.get_name(child))
            child = fdt.next_subnode(child, quiet=(libfdt.NOTFOUND,))
    visit(0, '/')
    return result

def below(path, roots):
    return any(path == root or path.startswith(root + '/') for root in roots)

def corrected(blob):
    fdt = libfdt.Fdt(blob)
    before = snapshot(fdt)
    compat = before['/'].get('compatible', b'').split(b'\0')
    if not {'lenovo,tbx505x'.encode(), 'qcom,sdm429'.encode()} <= set(compat):
        raise Unsupported('not a Lenovo M10 SDM429 DTB')
    cpu_nodes = {path: props for path, props in before.items()
                 if path.startswith('/cpus/') and props.get('device_type') == b'cpu\0'}
    ids = {}
    for path, props in cpu_nodes.items():
        address = cells(props['reg'])
        if len(address) != 1 or address[0] in ids:
            raise Unsupported('unexpected CPU address format')
        ids[address[0]] = path
    if set(ids) == KEEP:
        return blob, 'already corrected upstream'
    if set(ids) != KEEP | REMOVE:
        raise Unsupported('unexpected CPU inventory')
    for path, props in cpu_nodes.items():
        if props.get('compatible') != b'arm,cortex-a53\0' or props.get('enable-method') != b'psci\0':
            raise Unsupported('unexpected CPU implementation')
    removed = {ids[i] for i in REMOVE} | {'/cpus/cpu-map/cluster0'}
    for cluster, addresses in ((0, range(4)), (1, range(0x100, 0x104))):
        root = f'/cpus/cpu-map/cluster{cluster}'
        expected_paths = {root} | {root + f'/core{i}' for i in range(4)}
        if {p for p in before if below(p, {root})} != expected_paths or before[root]:
            raise Unsupported('unexpected CPU map structure')
        for i, address in enumerate(addresses):
            if before[root + f'/core{i}'] != {'cpu': cpu_nodes[ids[address]]['phandle']}:
                raise Unsupported('CPU map does not match physical addresses')
    if {p for p in before if p.startswith('/cpus/cpu-map/')} != {
            f'/cpus/cpu-map/cluster{c}' + suffix for c in range(2)
            for suffix in ('', '/core0', '/core1', '/core2', '/core3')}:
        raise Unsupported('additional CPU topology')
    removed_handles = {cells(props['phandle'])[0] for path, props in before.items()
                       if below(path, removed) and 'phandle' in props}
    for path, props in before.items():
        if below(path, removed):
            continue
        # Reject new references which would require a different, reviewed patch.
        for key in ('cpu', 'cpus', 'interrupt-affinity', 'next-level-cache'):
            if key in props and set(cells(props[key])) & removed_handles:
                raise Unsupported(f'remaining CPU/cache reference: {path}/{key}')
        if 'cooling-device' in props:
            values = cells(props['cooling-device'])
            index = 0
            while index < len(values):
                handle = values[index]
                if handle in removed_handles:
                    raise Unsupported(f'remaining cooling reference: {path}')
                target = fdt.node_offset_by_phandle(handle)
                index += 1 + cells(bytes(fdt.getprop(target, '#cooling-cells')))[0]
            if index != len(values):
                raise Unsupported('malformed cooling map')
    if '/__symbols__' in before or '/__fixups__' in before:
        raise Unsupported('symbol-bearing DTB requires separate handling')
    for path in sorted(removed):
        fdt.del_node(fdt.path_offset(path))
    fdt.set_name(fdt.path_offset('/cpus/cpu-map/cluster1'), 'cluster0')
    expected = {}
    for path, props in before.items():
        if not below(path, removed):
            if below(path, {'/cpus/cpu-map/cluster1'}):
                path = path.replace('/cpus/cpu-map/cluster1', '/cpus/cpu-map/cluster0', 1)
            expected[path] = props
    fdt.pack()
    if snapshot(fdt) != expected:
        raise Unsupported('unrelated device tree contents changed')
    return bytes(fdt.as_bytearray()), 'removed unavailable cluster; four CPUs remain'

def generate(source, destination):
    blob = source.read_bytes()
    try:
        result, status = corrected(blob)
    except (Unsupported, libfdt.FdtException, KeyError, ValueError, IndexError) as error:
        result, status = blob, 'using current official DTB unchanged: ' + str(error)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + destination.name + '.', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(result)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print('rpd-cpu-topology-m10: ' + status, file=sys.stderr)
    return status

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error('source must remain the unmodified official kernel DTB')
    generate(args.source, args.destination)
