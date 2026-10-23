#!/bin/sh
# Candidate-only native userspace packages; no production key or publication.
set -eu
case "${1:-}" in polkit|squeekboard) package=$1;; *) exit 2;; esac
[ "$(uname -m)" = aarch64 ] && [ "$(id -u)" = 0 ]
[ -f /etc/alpine-release ]
[ -f /.dockerenv ] || [ -f /run/.containerenv ]
[ -d /out ]
cd "$(dirname "$0")/.."
apk add --no-cache alpine-sdk python3 pkgconf sudo curl
install -m644 keys/build.postmarketos.org.rsa.pub /etc/apk/keys/
printf '\nhttps://mirror.postmarketos.org/postmarketos/extra-repos/systemd/main\n' >> /etc/apk/repositories
adduser -D builder
addgroup builder abuild
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-builder
export ABUILD_USERDIR=/home/builder/.abuild REPODEST=/home/builder/packages
mkdir -p "$ABUILD_USERDIR" /home/builder/rpd-security/ports
cp -a "ports/$package" /home/builder/rpd-security/ports/
install -m644 scripts/source-download.curlrc /home/builder/.curlrc
chown -R builder:builder /home/builder
su builder -c 'abuild-keygen -a -i -n'
cp "$ABUILD_USERDIR"/*.pub /etc/apk/keys/
su builder -c "cd /home/builder/rpd-security/ports/$package && abuild -r"

out="/out/$package"
mkdir -p "$out/aarch64" "$out/keys" "$out/sources"
cp "$REPODEST"/ports/aarch64/*.apk "$out/aarch64/"
cp "$REPODEST"/ports/aarch64/APKINDEX.tar.gz "$out/aarch64/"
cp "$ABUILD_USERDIR"/*.pub "$out/keys/"
cp /var/cache/distfiles/*.tar.* "$out/sources/"
for apkfile in "$out"/aarch64/*.apk; do apk verify "$apkfile"; done
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apk/keys"
cp /etc/apk/keys/*.pub "$root/etc/apk/keys/"
cp /etc/apk/repositories "$root/etc/apk/repositories"
printf '\n%s/ports\n' "$REPODEST" >> "$root/etc/apk/repositories"
version=$(python3 - "$out/aarch64" "$package" <<'PY'
from pathlib import Path
import re, sys
matches = [re.fullmatch(re.escape(sys.argv[2])+r'-([0-9][^-]*-r[0-9]+)\.apk', p.name)
           for p in Path(sys.argv[1]).glob('*.apk')]
versions = [m[1] for m in matches if m]
assert len(versions) == 1, versions
print(versions[0])
PY
)
apk --root "$root" --initdb --no-scripts add "$package=$version" "$package-systemd=$version" systemd
apk --root "$root" info -v > "$out/installed-packages.txt"
if grep -q '^systemd-stage0' "$out/installed-packages.txt"; then
    echo 'Build bootstrap packages leaked into the runtime root' >&2
    exit 1
fi
if [ "$package" = polkit ]; then
    chroot "$root" /usr/bin/pkaction --version
    test "$(stat -c %a "$root/usr/lib/polkit-1/polkit-agent-helper-1")" = 4755
    test -f "$root/usr/lib/systemd/system/polkit.service"
fi
printf '%s\n' "Native $package build/check, signatures and clean-root install passed" > "$out/validation.txt"
printf '%s\n' 'Candidate only: no production signing, publication or M10 qualification' >> "$out/validation.txt"
