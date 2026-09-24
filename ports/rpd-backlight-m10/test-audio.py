"""Check the board delta and kernel-update fallbacks using the real built DTBs."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import libfdt

spec = importlib.util.spec_from_file_location('audio', Path(__file__).with_name('audio-dtb.py'))
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)
topology = audio.topology_module(sys.argv[3] if len(sys.argv) > 3 else
                                '/usr/lib/rpd-cpu-topology-m10/topology.py')
base, candidate = (Path(x).read_bytes() for x in sys.argv[1:3])
before, after = (topology.snapshot(libfdt.Fdt(x)) for x in (base, candidate))

def handles(tree):
    return {int.from_bytes(p['phandle'], 'big'): n for n, p in tree.items()
            if 'phandle' in p}

old_handles, new_handles = handles(before), handles(after)
allowed = ('/soc@0/sound-card@c051000', '/soc@0/codec@c0f0000',
           '/soc@0/remoteproc@c200000/smd-edge/apr',
           '/soc@0/spmi@200f000/pmic@1/audio-codec@f000',
           '/soc@0/pinctrl@1000000/cdc-pdm-lines-',
           '/soc@0/pinctrl@1000000/speaker-',
           '/speaker-left-amplifier', '/speaker-right-amplifier')

for path, props in before.items():
    assert path in after, ('removed node', path)
    for name, old in props.items():
        new = after[path].get(name)
        if old == new or name == 'phandle':
            continue
        if new is not None and len(old) == len(new) and len(old) % 4 == 0:
            a, b = topology.cells(old), topology.cells(new)
            if all(x == y or x in old_handles and old_handles[x] == new_handles.get(y)
                   for x, y in zip(a, b)):
                continue
        assert path.startswith(allowed), ('unrelated property changed', path, name)
for path, props in after.items():
    for name in props.keys() - before.get(path, {}).keys():
        assert name == 'phandle' or path.startswith(allowed), ('unrelated addition', path, name)
assert after['/soc@0/sound-card@c051000']['status'] == b'okay\0'
assert after['/speaker-left-amplifier']['compatible'] == b'lenovo,tbx505-speaker-amp\0'
assert after['/speaker-right-amplifier']['compatible'] == b'lenovo,tbx505-speaker-amp\0'

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source, data, modules = root/'source.dtb', root/'data', root/'modules'
    data.mkdir()
    source.write_bytes(base)
    (data/'base.dtb').write_bytes(base)
    (data/'audio.dtb').write_bytes(candidate)
    (data/'kernel.json').write_text(json.dumps({'release': 'test', 'apk': '1-r0'}))
    folder = modules/'test/extra'
    folder.mkdir(parents=True)
    for name in ('m10_audio_pmic', 'm10_wcd_analog', 'm10_speaker_amp'):
        (folder/(name+'.ko')).touch()
    fallback = topology.corrected(base)[0]
    expected = topology.corrected(candidate)[0]
    assert audio.select(source, data, '1-r0', modules, topology)[0] == expected
    assert audio.select(source, data, '2-r0', modules, topology)[0] == fallback
    missing = folder/'m10_speaker_amp.ko'
    missing.unlink()
    assert audio.select(source, data, '1-r0', modules, topology)[0] == fallback
    missing.touch()
    changed = libfdt.Fdt(base)
    changed.resize(len(base) + 512)
    changed.setprop_str(0, 'model', 'Future official M10 board revision')
    changed.pack()
    source.write_bytes(bytes(changed.as_bytearray()))
    assert audio.select(source, data, '1-r0', modules, topology)[0] == topology.corrected(source.read_bytes())[0]
    assert b'Future official M10 board revision' in audio.select(source, data, '2-r0', modules, topology)[0]
print('Audio DT delta, matching selection, missing-module and kernel/DT upgrade fallbacks passed')
