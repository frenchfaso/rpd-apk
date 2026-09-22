import tempfile
from pathlib import Path
import unittest
import libfdt
from topology import corrected, generate, snapshot, Unsupported


def fixture():
    tree = libfdt.Fdt.create_empty_tree(16384)
    def node(path):
        if path == '/':
            return 0
        parent, name = path.rsplit('/', 1)
        try:
            return tree.path_offset(path)
        except libfdt.FdtException:
            tree.add_subnode(node(parent or '/'), name)
            return tree.path_offset(path)
    def prop(path, name, value):
        offset = node(path)
        if isinstance(value, int):
            tree.setprop_u32(offset, name, value)
        else:
            tree.setprop(offset, name, value)
    prop('/', 'compatible', b'lenovo,tbx505x\0qcom,sdm429\0')
    prop('/cpus', '#address-cells', 1)
    prop('/cpus', '#size-cells', 0)
    for cluster in range(2):
        for core in range(4):
            address = cluster * 0x100 + core
            cpu = f'/cpus/cpu@{address:x}'
            prop(cpu, 'reg', address)
            prop(cpu, 'phandle', address + 16)
            prop(cpu, 'device_type', b'cpu\0')
            prop(cpu, 'compatible', b'arm,cortex-a53\0')
            prop(cpu, 'enable-method', b'psci\0')
            prop(f'/cpus/cpu-map/cluster{cluster}/core{core}', 'cpu', address + 16)
    prop('/soc', 'unrelated-data', b'preserve this\0')
    tree.pack()
    return bytes(tree.as_bytearray())


def changed(blob, path, prop, data):
    tree = libfdt.Fdt(blob)
    tree.resize(len(blob) + 1024)
    tree.setprop(tree.path_offset(path), prop, data)
    tree.pack()
    return bytes(tree.as_bytearray())


class TopologyTests(unittest.TestCase):
    def test_four_cpus_and_contiguous_cluster(self):
        result, _ = corrected(fixture())
        props = snapshot(libfdt.Fdt(result))
        self.assertEqual({p for p, v in props.items() if v.get('device_type') == b'cpu\0'},
                         {f'/cpus/cpu@{x:x}' for x in range(0x100, 0x104)})
        self.assertNotIn('/cpus/cpu-map/cluster1', props)
        self.assertEqual(props['/cpus/cpu-map/cluster0/core0']['cpu'], (0x110).to_bytes(4, 'big'))
        self.assertEqual(props['/soc']['unrelated-data'], b'preserve this\0')

    def test_upstream_fixed_is_byte_identical(self):
        result, _ = corrected(fixture())
        again, status = corrected(result)
        self.assertEqual(again, result)
        self.assertIn('upstream', status)

    def test_unrelated_kernel_update_is_preserved(self):
        blob = changed(fixture(), '/soc', 'unrelated-data', b'new driver data\0')
        result, _ = corrected(blob)
        self.assertEqual(snapshot(libfdt.Fdt(result))['/soc']['unrelated-data'], b'new driver data\0')

    def test_other_board_is_rejected(self):
        with self.assertRaises(Unsupported):
            corrected(changed(fixture(), '/', 'compatible', b'other,board\0'))

    def test_new_reference_is_rejected(self):
        blob = changed(fixture(), '/soc', 'interrupt-affinity', (16).to_bytes(4, 'big'))
        with self.assertRaises(Unsupported):
            corrected(blob)

    def test_unexpected_cpu_map_is_rejected(self):
        blob = changed(fixture(), '/cpus/cpu-map/cluster1/core0', 'cpu', (16).to_bytes(4, 'big'))
        with self.assertRaises(Unsupported):
            corrected(blob)

    def test_failure_replaces_stale_copy_with_current_official(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/'official', Path(tmp)/'derived'
            source.write_bytes(fixture())
            generate(source, dest)
            newer = changed(fixture(), '/', 'compatible', b'other,board\0')
            source.write_bytes(newer)
            generate(source, dest)
            self.assertEqual(dest.read_bytes(), newer)
            self.assertEqual(source.read_bytes(), newer)

    def test_repeated_kernel_deploy_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/'official', Path(tmp)/'derived'
            original = fixture()
            source.write_bytes(original)
            generate(source, dest)
            expected = dest.read_bytes()
            generate(source, dest)
            self.assertEqual(dest.read_bytes(), expected)
            self.assertEqual(source.read_bytes(), original)

unittest.main()
