#!/bin/sh
# Validate the installed dependency closure without running privileged helpers.
set -eu
root=$1
cd "$(dirname "$0")/.."
for requirement in 'webkit2gtk-6.0>=2.54.2' 'squeekboard>=1.43.1-r171' \
    'polkit>=9999127-r100' 'linux-postmarketos-qcom-msm89x7>=7.1.3-r100' \
    systemd polkit-systemd squeekboard-systemd; do
    apk --root "$root" info --installed -e "$requirement" >/dev/null
done
if apk --root "$root" info --installed | grep -q '^systemd-stage0'; then
    echo 'Build bootstrap packages leaked into the runtime root' >&2
    exit 1
fi
cmp "$root/usr/share/kernel/postmarketos-qcom-msm89x7/rpd-security-fixes.json" ports/linux-postmarketos-qcom-msm89x7/security-fixes.json
chroot "$root" /usr/bin/pkaction --version >/dev/null
chroot "$root" /usr/bin/python3 - <<'PY'
import ctypes
import json
from pathlib import Path
import stat

library = ctypes.CDLL('libwebkitgtk-6.0.so.4')
version = []
for component in ['major', 'minor', 'micro']:
    function = getattr(library, 'webkit_get_' + component + '_version')
    function.restype = ctypes.c_uint
    version.append(function())
assert tuple(version) >= (2, 54, 2), version
kernel = Path('/usr/share/kernel/postmarketos-qcom-msm89x7')
security = json.loads((kernel/'rpd-security-fixes.json').read_text())
release = (kernel/'kernel.release').read_text().strip()
assert release == security['kernel_release']
expected = {'release': release, 'apk': security['kernel_apk_version']}
modules = {}
for name in ['rpd-gpu-m10', 'rpd-audio-m10', 'rpd-battery-m10',
             'rpd-charger-m10', 'rpd-usb-otg-m10']:
    modules[name] = json.loads((Path('/usr/lib')/name/'kernel.json').read_text())
    assert modules[name] == expected, (name, modules[name], expected)
loader = Path('/usr/libexec/rpd-backlight-m10-load').read_text()
assert '\nexpected_apk=' + expected['apk'] + '\n' in loader
assert len(security['fixes']) >= 8
for name in ['/usr/lib/polkit-1/polkit-agent-helper-1', '/usr/bin/pkexec']:
    info = Path(name).stat()
    assert info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o4755, name
for name in ['/usr/lib/systemd/system/polkit.service',
             '/usr/lib/systemd/user/mobi.phosh.OSK.service']:
    assert Path(name).is_file(), name
print(json.dumps({'status': 'SECURITY_RUNTIME_VERIFIED', 'webkit': version,
                  'kernel': expected, 'modules': modules}, indent=2))
PY
