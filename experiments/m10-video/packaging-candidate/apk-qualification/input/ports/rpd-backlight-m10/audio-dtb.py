#!/usr/bin/python3
"""Select M10 audio only for the matching installed kernel and official DTB."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

def topology_module(path):
    spec = importlib.util.spec_from_file_location('topology', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def select(source, data, installed_apk, modules, topology):
    import libfdt
    official = source.read_bytes()
    # Always start from the new official tree, never yesterday's audio output.
    fallback, _ = topology.corrected(official)
    metadata = json.loads((data / 'kernel.json').read_text())
    if installed_apk != metadata['apk']:
        return fallback, 'kernel APK changed; audio disabled until rebuilt'
    for name in ('m10_audio_pmic', 'm10_wcd_analog', 'm10_speaker_amp'):
        if not (modules / metadata['release'] / 'extra' / (name + '.ko')).is_file():
            return fallback, 'matching audio modules unavailable'
    before = topology.snapshot(libfdt.Fdt(official))
    expected = topology.snapshot(libfdt.Fdt((data / 'base.dtb').read_bytes()))
    if before != expected:
        return fallback, 'official DTB changed; audio disabled until rebuilt'
    candidate = (data / 'audio.dtb').read_bytes()
    selected, _ = topology.corrected(candidate)
    return selected, 'matching PM8953 stereo speaker support enabled'

def main():
    source = Path('/boot/dtbs/qcom/sdm429-lenovo-tbx505x.dtb')
    output = Path('/boot/dtbs/rpd/sdm429-lenovo-tbx505x.dtb')
    data = Path('/usr/lib/rpd-audio-m10')
    if not source.is_file():
        return
    topology = topology_module('/usr/lib/rpd-cpu-topology-m10/topology.py')
    # This also provides a safe current-kernel fallback on any later failure.
    topology.generate(source, output)
    try:
        metadata = json.loads((data / 'kernel.json').read_text())
        matched = subprocess.run(['apk', 'info', '-e',
            'linux-postmarketos-qcom-msm89x7=' + metadata['apk']],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=20).returncode == 0
        blob, message = select(source, data, metadata['apk'] if matched else '',
                               Path('/usr/lib/modules'), topology)
        tmp = output.with_suffix('.audio.tmp')
        tmp.write_bytes(blob)
        tmp.chmod(0o644)
        tmp.replace(output)
        print('rpd-audio-m10: ' + message, file=sys.stderr)
    except Exception as error:
        print('rpd-audio-m10: using current kernel without audio: ' + str(error),
              file=sys.stderr)

if __name__ == '__main__':
    main()
