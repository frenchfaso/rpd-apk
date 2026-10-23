#!/bin/sh
# Artifact-only native build, restricted to the disposable Alpine CI container.
set -eu
[ "${RPD_DISPOSABLE_BUILD:-}" = 1 ]
[ "$(id -u)" = 0 ]
[ "$(uname -s)" = Linux ]
[ "$(uname -m)" = aarch64 ]
[ -f /etc/alpine-release ]
[ -f /.dockerenv ]
[ -d /out ]
export ABUILD_USERDIR=/home/builder/.abuild
export REPODEST=/home/builder/packages

mkdir -p /out/reports /out/sources /out/keys /out/aarch64
{
    uname -a
    cat /etc/alpine-release
    nproc
    cat /proc/meminfo
    for path in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
        if [ -f "$path" ]; then printf '%s: ' "$path"; cat "$path"; fi
    done
    df -k / /out
} > /out/reports/resources-before.txt
apk add --no-cache alpine-sdk python3 git sudo curl time
python3 -m unittest discover -s /work/tests -p test_webkit_candidate.py

adduser -D builder
addgroup builder abuild
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-webkit-builder
mkdir -p /home/builder/.abuild /home/builder/packages /home/builder/ports
install -m644 /work/scripts/source-download.curlrc /home/builder/.curlrc
cp -a /work/ports/webkit2gtk-6.0 /home/builder/ports/
chown -R builder:builder /home/builder
su builder -c 'abuild-keygen -a -i -n'
cp /home/builder/.abuild/*.pub /etc/apk/keys/

collect() {
    if [ -d /home/builder/ports/webkit2gtk-6.0/build-evidence ]; then
        cp -a /home/builder/ports/webkit2gtk-6.0/build-evidence/. /out/reports/
    fi
    df -k / /out > /out/reports/resources-after.txt
}
trap 'result=$?; trap - EXIT; collect || :; exit "$result"' EXIT
/usr/bin/time -v -o /out/reports/build-resources.txt \
    su builder -c 'cd /home/builder/ports/webkit2gtk-6.0 && abuild -r'

cp /home/builder/packages/ports/aarch64/*.apk /out/aarch64/
cp /home/builder/packages/ports/aarch64/APKINDEX.tar.gz /out/aarch64/
cp /home/builder/.abuild/*.pub /out/keys/
apk verify /out/aarch64/*.apk
cp /var/cache/distfiles/webkitgtk-*.tar.xz /out/sources/
cp /work/ports/webkit2gtk-6.0/upstream.json /out/sources/

# Install only inside this throwaway container, authenticating with its local key.
# Epiphany's normal package resolution must accept the replacement GTK4 ABI.
apk add --no-cache epiphany /out/aarch64/webkit2gtk-6.0-[0-9]*.apk
version=$(python3 -c 'import json; print(json.load(open("/work/ports/webkit2gtk-6.0/upstream.json"))["version"])')
python3 /work/ports/webkit2gtk-6.0/verify-build.py runtime --version "$version" \
    > /out/reports/installed-runtime.json
apk info -v > /out/reports/installed-packages.txt
scanelf -n /usr/bin/epiphany > /out/reports/epiphany-abi.txt
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

output = Path('/out')
files = {}
for path in sorted(output.rglob('*')):
    if path.is_file() and path.suffix in ('.apk', '.pub'):
        files[str(path.relative_to(output))] = hashlib.sha512(path.read_bytes()).hexdigest()
receipt = {
    'source_revision': os.environ.get('RPD_SOURCE_REVISION', 'unknown'),
    'source_date_epoch': os.environ.get('SOURCE_DATE_EPOCH'),
    'signing': 'Ephemeral abuild key; no production key or publication.',
    'sha512': files,
    'qualification': 'Native ARM64 configuration, signed APKs and loaded library ABI only. '
                     'Browser sandbox runtime, FD504 WebGL and Venus decode require device tests.',
}
(output / 'reports/receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
PY
