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
# The runtime theme must not pull GTK headers and their development toolchain.
! apk --root "$root" info | grep -E '^(rpd-gtk2-engine-dev|gtk\+2\.0-dev)$'
for path in usr/bin/chromium usr/bin/rpd-browser usr/sbin/rpd-configure-host usr/libexec/rpd-system-settings usr/share/raspi-ui-overrides/applications/mimeinfo.cache usr/lib/chromium/initial_preferences etc/chromium/policies/recommended/rpd.json usr/bin/vlc usr/bin/rpd-localisation usr/bin/rpd-apply-greeter usr/lib/rpcc/librpcc_raindrop.so usr/lib/rpcc/librpcc_rpinters.so usr/lib/rpcc/librpcc_rc_gui.so usr/bin/rpcc usr/bin/lxtask usr/bin/gui-runcmd usr/bin/gui-screenshot usr/bin/galculator usr/bin/eom usr/bin/evince usr/lib/wf-panel-pi/libsmenu.so usr/lib/rpcc/librpcc_pipanel.so usr/lib/rpcc/librpcc_wf-panel-pi.so usr/bin/wf-panel-pi usr/bin/pcmanfm usr/bin/rpd-session usr/bin/squeekboard usr/bin/labwc usr/lib/wf-panel-pi/libnmenu.so usr/lib/wf-panel-pi/libtlist.so usr/lib/wf-panel-pi/libsqueek.so usr/lib/wf-panel-pi/libejecter.so usr/lib/wf-panel-pi/libnetman.so usr/lib/wf-panel-pi/libvolumepulse.so usr/lib/wf-panel-pi/libbatt.so usr/bin/xdg-user-dirs-update usr/bin/udisksctl usr/libexec/gvfs/gvfs-udisks2-volume-monitor usr/libexec/polkit-mate-authentication-agent-1 usr/bin/pishutdown usr/lib/wf-panel-pi/libbluetooth.so usr/sbin/pi-greeter usr/bin/rpd-greeter-session usr/share/xgreeters/rpd-greeter-labwc.desktop; do
    test -f "$root/$path" || { echo "Missing $path" >&2; exit 1; }
done
apk --root "$root" info -s > out/installed-sizes.txt
apk --root "$root" info > out/installed-packages.txt
# Version and shared-library load checks in the native clean root.
chroot "$root" /usr/bin/labwc --version
chroot "$root" /usr/bin/pcmanfm --help >/dev/null
chroot "$root" /usr/bin/lightdm --show-config > out/lightdm-config.txt 2>&1
grep -q 'greeter-session=rpd-greeter-labwc' out/lightdm-config.txt
grep -q 'user-session=rpd-session-m10' out/lightdm-config.txt
printf 'Clean-root dependency and executable checks passed\n' > out/validation.txt

apk add --upgrade rpd-desktop-m10 grim procps wlrctl gtk-layer-shell-rpd-test
# Provide a real system D-Bus for service activation in the disposable test.
mkdir -p /run/dbus
dbus-uuidgen --ensure
[ -S /run/dbus/system_bus_socket ] || dbus-daemon --system --fork
# Mesa/libseat do not permit root sessions; use the existing builder account.
su builder -c "cd /home/builder/rpd-build && RPD_TWO_FINGER_RIGHT_CLICK=1 sh scripts/headless.sh"
cp /tmp/rpd-vlc.png /tmp/rpd-vlc.log /tmp/rpd-headless.log /tmp/rpd-headless.png /tmp/rpd-keyboard.png /tmp/rpd-classic-menu.png /tmp/rpd-control-center.png /tmp/rpd-control-center.log out/
printf 'Native headless compositor test passed\n' >> out/validation.txt

sh scripts/greeter-smoke.sh
