#!/usr/bin/python3
"""Compose the verified Adreno 504 change after the current audio/CPU hooks."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import libfdt


def enable(blob, topology):
    fdt = libfdt.Fdt(blob)
    before = topology.snapshot(fdt)
    assert before['/']['compatible'] == b'lenovo,tbx505x\0qcom,sdm429\0'
    gpu = '/soc@0/gpu@1c00000'
    opp = gpu + '/opp-table'
    assert before[gpu]['status'] == b'disabled\0'
    assert before[gpu]['compatible'] == b'qcom,adreno-505.0\0qcom,adreno\0'
    rpm = [p for p, v in before.items() if b'qcom,sdm439-rpmpd\0' in v.get('compatible', b'')]
    assert len(rpm) == 1
    rpm = rpm[0]
    svs = rpm + '/opp-table/opp5'
    assert before[svs]['opp-level'] == struct.pack('>I', 128)
    fdt.resize(fdt.totalsize() + 1024)
    fdt.setprop(fdt.path_offset(gpu), 'compatible', b'qcom,adreno-504.0\0qcom,adreno\0')
    fdt.setprop_str(fdt.path_offset(gpu), 'status', 'okay')
    # SDM439_VDDCX = 1; attach CX first to map required-opps index 0.
    fdt.setprop(fdt.path_offset(gpu), 'power-domains', before[rpm]['phandle'] + struct.pack('>I', 1) + before[gpu]['power-domains'])
    fdt.setprop(fdt.path_offset(gpu), 'power-domain-names', b'cx\0gx\0')
    for path in before:
        if path.startswith(opp+'/'):
            assert 'phandle' not in before[path]
            fdt.del_node(fdt.path_offset(path))
    for freq in (19200000, 50000000, 320000000):
        offset = fdt.add_subnode(fdt.path_offset(opp), f'opp-{freq}')
        fdt.setprop(offset, 'opp-hz', struct.pack('>Q', freq))
        fdt.setprop(offset, 'opp-supported-hw', struct.pack('>I', 0xff))
        fdt.setprop(offset, 'required-opps', before[svs]['phandle'])
    fdt.pack()
    after = topology.snapshot(fdt)
    for path, props in before.items():
        if not path.startswith(gpu):
            assert after.get(path) == props, ('unrelated node changed', path)
    assert not [p for p in set(after)-set(before) if not p.startswith(opp+'/')]
    assert len([p for p in after if p.startswith(opp+'/')]) == 3
    return bytes(fdt.as_bytearray())


def select(source, composed, data, installed_apk, topology):
    metadata = json.loads((data / 'kernel.json').read_text())
    if installed_apk != metadata['apk']:
        return composed, 'kernel changed; using its current DT without GPU changes'
    for name in ('msm.ko', 'ubwc_config.ko'):
        if not (data / name).is_file():
            return composed, 'matching GPU modules unavailable'
    if topology.snapshot(libfdt.Fdt(source)) != topology.snapshot(
            libfdt.Fdt((data / 'base.dtb').read_bytes())):
        return composed, 'official DT changed; GPU extension skipped'
    return enable(composed, topology), 'Adreno 504 enabled, capped at 320 MHz'


def main():
    source = Path('/boot/dtbs/qcom/sdm429-lenovo-tbx505x.dtb')
    output = Path('/boot/dtbs/rpd/sdm429-lenovo-tbx505x.dtb')
    data = Path('/usr/lib/rpd-gpu-m10')
    if not source.is_file() or not output.is_file():
        return
    # Hook 95 has just composed this kernel's audio/CPU tree. Do not replace it
    # with an old complete DTB or discard other device support on GPU failure.
    try:
        spec = importlib.util.spec_from_file_location('topology',
            '/usr/lib/rpd-cpu-topology-m10/topology.py')
        topology = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(topology)
        metadata = json.loads((data / 'kernel.json').read_text())
        matched = subprocess.run(['apk', 'info', '-e',
            'linux-postmarketos-qcom-msm89x7=' + metadata['apk']],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20).returncode == 0
        blob, message = select(source.read_bytes(), output.read_bytes(), data,
                               metadata['apk'] if matched else '', topology)
        tmp = output.with_suffix('.gpu.tmp')
        tmp.write_bytes(blob)
        tmp.chmod(0o644)
        tmp.replace(output)
        print('rpd-gpu-m10: ' + message, file=sys.stderr)
    except Exception as error:
        print('rpd-gpu-m10: leaving current audio/CPU tree: ' + str(error),
              file=sys.stderr)


if __name__ == '__main__':
    main()
