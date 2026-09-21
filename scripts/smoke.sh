#!/bin/sh
set -eu
# Dependency resolution and file conflicts are checked in a clean root, not the build root.
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apk/keys"
cp /etc/apk/keys/*.pub "$root/etc/apk/keys/"
cp /etc/apk/repositories "$root/etc/apk/repositories"
apk --root "$root" --initdb --no-scripts add rpd-desktop-m10
! apk --root "$root" info | grep -E '^(raspi-config|raspberrypi-bootloader|linux-rpi|rpi-eeprom|apt|dpkg)$'
for path in usr/bin/wf-panel-pi usr/bin/pcmanfm usr/bin/rpd-session usr/bin/squeekboard usr/bin/labwc usr/lib/wf-panel-pi/libnmenu.so usr/lib/wf-panel-pi/libtlist.so usr/lib/wf-panel-pi/libsqueek.so; do
    test -f "$root/$path" || { echo "Missing $path" >&2; exit 1; }
done
apk --root "$root" info -s > out/installed-sizes.txt
apk --root "$root" info > out/installed-packages.txt
# Version and shared-library load checks in the native clean root.
chroot "$root" /usr/bin/labwc --version
chroot "$root" /usr/bin/pcmanfm --help >/dev/null
printf 'Clean-root dependency and executable checks passed\n' > out/validation.txt

apk add rpd-desktop-m10 grim procps
# Mesa/libseat do not permit root sessions; use the existing builder account.
su builder -c "cd /home/builder/rpd-build && sh scripts/headless.sh"
cp /tmp/rpd-headless.log /tmp/rpd-headless.png out/
printf 'Native headless compositor test passed\n' >> out/validation.txt
