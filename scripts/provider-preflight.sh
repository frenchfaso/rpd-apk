#!/bin/sh
# Native disposable diagnostic only: compile GTK, never Mesa/labwc/kernel.
set -eu
case "${MODE:-}" in baseline|real-systemd|exact-files) ;; *) exit 2;; esac
[ "$(uname -m)" = aarch64 ]
[ -z "${RPD_SIGNING_KEY:-}" ] && [ -z "${APK_SIGNING_KEY:-}" ]
[ -d /out ] && [ -r /work/scripts/build.sh ]
export ABUILD_USERDIR=/home/builder/.abuild REPODEST=/home/builder/packages
export RPD_DISPOSABLE_BUILD=1 JOBS=2
phase=bootstrap
snapshot() {
    name=$1
    mkdir -p "/out/$name"
    cp /etc/apk/world "/out/$name/world"
    cp /lib/apk/db/installed "/out/$name/installed-db"
    apk info -v > "/out/$name/installed-packages.txt"
    apk policy systemd systemd-dev systemd-stage0 systemd-stage0-dev eudev-dev elogind-dev \
        > "/out/$name/provider-policy.txt" 2>&1 || true
    for path in /usr/include/libudev.h /usr/lib/libudev.so /usr/lib/pkgconfig/libudev.pc; do
        apk info --who-owns "$path" >> "/out/$name/ownership.txt" 2>&1 || true
    done
}
finish() {
    code=$1
    snapshot final
    printf '{"mode":"%s","exit_code":%s,"last_phase":"%s","scope":"APK provider closure only; full desktop/runtime/headless/greeter gates still required"}\n' \
        "$MODE" "$code" "$phase" > /out/result.json
}
trap 'finish $?' EXIT
capture() {
    label=$1; shift
    if "$@" > "/out/$label.log" 2>&1; then
        cat "/out/$label.log"
    else
        code=$?; cat "/out/$label.log"; return "$code"
    fi
}
installed() { grep -qx "P:$1" /lib/apk/db/installed; }
real_provider() {
    installed systemd || return 1
    installed systemd-dev || return 1
    if grep -q '^P:systemd-stage0' /lib/apk/db/installed; then return 1; fi
    for path in /usr/include/libudev.h /usr/lib/libudev.so /usr/lib/pkgconfig/libudev.pc; do
        apk info --who-owns "$path" | grep -F ' owned by systemd-dev-' || return 1
    done
}
eudev_provider() {
    installed eudev-dev || return 1
    installed elogind-dev || return 1
    if installed systemd-dev; then return 1; fi
    if grep -q '^P:systemd-stage0' /lib/apk/db/installed; then return 1; fi
    for path in /usr/include/libudev.h /usr/lib/libudev.so /usr/lib/pkgconfig/libudev.pc; do
        apk info --who-owns "$path" | grep -F ' owned by eudev-dev-' || return 1
    done
}
cd /work
sha256sum -c /dev/stdin > /out/canonical-inputs.txt <<'HASHES'
29e297ae457d85c3f206db9cd5dbc58c13874a1495c1f76ca6254a7415929fd1  scripts/build.sh
b0c00600029f2f290f58ed7d6b69b9e76542b22d926baec7b780d2bd7bef42e7  ports/labwc/APKBUILD
18ad8d700b4ea421e3eac250a600af1c5ba418e9ac48504e3dfc0ac8af1cee8c  ports/gtk-layer-shell/APKBUILD
HASHES
capture bootstrap apk add --no-cache alpine-sdk abuild-rootbld meson samurai python3 git sudo curl
install -m644 keys/build.postmarketos.org.rsa.pub /etc/apk/keys/
printf '\nhttps://mirror.postmarketos.org/postmarketos/extra-repos/systemd/main\n' >> /etc/apk/repositories
python3 - <<'PY'
import os,re,json
from pathlib import Path
source=Path('scripts/build.sh').read_text()
lines=[line for line in source.splitlines() if line.startswith('apk add --no-cache pkgconf ')]
assert len(lines)==1
shared=lines[0].split()[3:]
assert shared.count('eudev-dev')==1
original=shared[:]
if os.environ['MODE']=='real-systemd':
    shared=[p for p in shared if p!='eudev-dev']+['systemd','systemd-dev']
recipe=Path('ports/labwc/APKBUILD').read_text()
deps=['build-base']
for field in ('depends','makedepends','checkdepends'):
    value=re.findall(r'^'+field+r'="([^"]*)"',recipe,re.M)
    assert len(value)==1 and re.fullmatch(r'[A-Za-z0-9_+.:@<>=~\s-]*',value[0])
    deps+=value[0].split()
Path('/out/shared-dependencies.txt').write_text(' '.join(shared)+'\n')
Path('/out/labwc-dependencies.txt').write_text(' '.join(deps)+'\n')
Path('/out/input-policy.json').write_text(json.dumps({'base_source':'f095a0e64f4be40b6bc926a871f14d9d30a24eb4','diagnostic_source':os.environ['ABUILD_LAST_COMMIT'],'mode':os.environ['MODE'],'original_shared':original,'selected_shared':shared,'labwc_build_closure':deps},indent=2)+'\n')
PY
phase=shared-world
# Intentional splitting: package tokens were read as data, never shell-evaluated.
capture shared-world apk add --no-cache $(cat /out/shared-dependencies.txt)
snapshot initial
real_provider > /out/initial-real-provider.txt
phase=labwc-closure
# The original loop updates indexes between ports; --no-cache above retains none.
capture before-labwc-index apk update
capture labwc-add apk add --virtual .makedepends-labwc $(cat /out/labwc-dependencies.txt)
snapshot labwc-added
capture labwc-clean apk del .makedepends-labwc
snapshot labwc-cleaned
if [ "$MODE" = real-systemd ]; then real_provider; else eudev_provider; fi
phase=gtk-build
adduser -D builder
addgroup builder abuild
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-builder
mkdir -p /home/builder/.abuild /home/builder/packages /home/builder/ports
install -m644 scripts/source-download.curlrc /home/builder/.curlrc
cp -a ports/gtk-layer-shell /home/builder/ports/
chown -R builder:builder /home/builder
# Standard throwaway abuild signing only; no production key or signature bypass.
capture keygen su builder -c 'abuild-keygen -a -i -n'
cp /home/builder/.abuild/*.pub /etc/apk/keys/
capture gtk-build su builder -c 'cd /home/builder/ports/gtk-layer-shell && abuild -r'
printf '\n/home/builder/packages/ports\n' >> /etc/apk/repositories
capture gtk-index apk update
mkdir -p /out/aarch64 /out/keys /out/sources
cp "$REPODEST"/ports/aarch64/*.apk /out/aarch64/
cp /home/builder/.abuild/*.pub /out/keys/
cp /var/cache/distfiles/gtk-layer-shell-*.tar.gz /out/sources/
capture gtk-signatures apk verify /out/aarch64/*.apk
set -- "$REPODEST"/ports/aarch64/gtk-layer-shell-[0-9]*.apk
[ "$#" -eq 1 ] && [ -f "$1" ]
main=$1
set -- "$REPODEST"/ports/aarch64/gtk-layer-shell-dev-[0-9]*.apk
[ "$#" -eq 1 ] && [ -f "$1" ]
dev=$1
snapshot before-transaction
if [ "$MODE" = real-systemd ]; then real_provider; else eudev_provider; fi
phase=gtk-transaction
if [ "$MODE" = exact-files ]; then
    set -- apk add "$main" "$dev"
    capture gtk-plan apk add --simulate "$main" "$dev"
else
    set -- apk add --upgrade gtk-layer-shell gtk-layer-shell-dev
    capture gtk-plan apk add --simulate --upgrade gtk-layer-shell gtk-layer-shell-dev
fi
if capture gtk-transaction "$@"; then result=0; else result=$?; fi
if [ "$MODE" = baseline ]; then
    [ "$result" -ne 0 ]
    grep -E 'systemd-stage0-dev.*trying to overwrite.*usr/include/libudev.h' /out/gtk-transaction.log
    grep -F 'owned by eudev-dev-' /out/gtk-transaction.log
    phase=baseline-collision-reproduced
else
    [ "$result" -eq 0 ]
    apk info -e gtk-layer-shell=0.10.1-r196
    apk info -e gtk-layer-shell-dev=0.10.1-r196
    [ "$(pkg-config --modversion gtk-layer-shell-0)" = 0.10.1 ]
    if [ "$MODE" = real-systemd ]; then real_provider; else eudev_provider; fi
    python3 - <<'PY'
from pathlib import Path
import json
def packages(path):
    rows={}
    for block in path.read_text().split('\n\n'):
        fields=dict(line.split(':',1) for line in block.splitlines() if line.startswith(('P:','V:')))
        if fields: rows[fields['P']]=fields['V']
    return rows
before=packages(Path('/out/before-transaction/installed-db'))
after=packages(Path('/lib/apk/db/installed'))
changed={name:[before.get(name),after.get(name)] for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
assert set(changed)=={'gtk-layer-shell','gtk-layer-shell-dev'},changed
assert all(after[name]=='0.10.1-r196' for name in changed)
Path('/out/exact-package-changes.json').write_text(json.dumps(changed,indent=2)+'\n')
PY
    phase=candidate-provider-transaction-passed
fi
