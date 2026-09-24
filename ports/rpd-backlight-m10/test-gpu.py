"""Exercise composition and update fallbacks with the built board DTs."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import libfdt


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpu = load('gpu', Path(__file__).with_name('gpu-dtb.py'))
topology = load('topology', sys.argv[3] if len(sys.argv) > 3 else
                '/usr/lib/rpd-cpu-topology-m10/topology.py')
base, audio = (Path(p).read_bytes() for p in sys.argv[1:3])
composed = topology.corrected(audio)[0]
with tempfile.TemporaryDirectory() as temporary:
    data = Path(temporary)
    (data/'base.dtb').write_bytes(base)
    (data/'kernel.json').write_text(json.dumps({'release':'test', 'apk':'1-r0'}))
    for name in ('msm.ko', 'ubwc_config.ko'):
        (data/name).touch()
    result, _ = gpu.select(base, composed, data, '1-r0', topology)
    before, after = (topology.snapshot(libfdt.Fdt(x)) for x in (composed, result))
    gpu_path = '/soc@0/gpu@1c00000'
    assert after[gpu_path]['compatible'].split(b'\0')[0] == b'qcom,adreno-504.0'
    assert after[gpu_path]['status'] == b'okay\0'
    assert {int.from_bytes(p['opp-hz'], 'big') for n,p in after.items()
            if n.startswith(gpu_path+'/opp-table/')} == {19200000,50000000,320000000}
    assert {n:p for n,p in before.items() if not n.startswith(gpu_path)} == {
            n:p for n,p in after.items() if not n.startswith(gpu_path)}
    assert gpu.select(base, composed, data, '2-r0', topology)[0] == composed
    (data/'msm.ko').unlink()
    assert gpu.select(base, composed, data, '1-r0', topology)[0] == composed
    (data/'msm.ko').touch()
    changed = libfdt.Fdt(base)
    changed.resize(len(base)+512)
    changed.setprop_str(0, 'model', 'New official board description')
    changed.pack()
    assert gpu.select(bytes(changed.as_bytearray()), composed, data,
                      '1-r0', topology)[0] == composed
    assert before['/soc@0/sound-card@c051000']['status'] == b'okay\0'
print('GPU composition preserves audio/CPU; kernel, DT and missing-module fallbacks passed')
