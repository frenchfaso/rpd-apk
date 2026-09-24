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
for path in usr/lib/udev/rules.d/99-rpd-m10-storage.rules usr/share/mkinitfs/hooks/20-rpd-lvm-m10.sh usr/lib/rpd-cpu-topology-m10/topology.py usr/share/boot-deploy/hooks/90-rpd-cpu-topology-m10 etc/deviceinfo usr/bin/rpd-autorotate usr/lib/rpd-autorotate/main.py etc/xdg/rpd/autorotate.conf usr/bin/chromium usr/bin/rpd-browser usr/sbin/rpd-configure-host usr/libexec/rpd-system-settings usr/share/raspi-ui-overrides/applications/mimeinfo.cache usr/lib/chromium/initial_preferences etc/chromium/policies/recommended/rpd.json usr/bin/vlc usr/bin/rpd-localisation usr/bin/rpd-apply-greeter usr/lib/rpcc/librpcc_raindrop.so usr/lib/rpcc/librpcc_rpinters.so usr/lib/rpcc/librpcc_rc_gui.so usr/bin/rpcc usr/bin/lxtask usr/bin/gui-runcmd usr/bin/gui-screenshot usr/bin/galculator usr/bin/eom usr/bin/evince usr/lib/wf-panel-pi/libsmenu.so usr/lib/rpcc/librpcc_pipanel.so usr/lib/rpcc/librpcc_wf-panel-pi.so usr/bin/wf-panel-pi usr/bin/pcmanfm usr/bin/rpd-session usr/bin/squeekboard usr/bin/labwc usr/lib/wf-panel-pi/libnmenu.so usr/lib/wf-panel-pi/libtlist.so usr/lib/wf-panel-pi/libsqueek.so usr/lib/wf-panel-pi/libejecter.so usr/lib/wf-panel-pi/libnetman.so usr/lib/wf-panel-pi/libvolumepulse.so usr/lib/wf-panel-pi/libbatt.so usr/bin/xdg-user-dirs-update usr/bin/udisksctl usr/libexec/gvfs/gvfs-udisks2-volume-monitor usr/libexec/polkit-mate-authentication-agent-1 usr/bin/pishutdown usr/lib/wf-panel-pi/libbluetooth.so usr/sbin/pi-greeter usr/bin/rpd-greeter-session usr/share/xgreeters/rpd-greeter-labwc.desktop; do
    test -f "$root/$path" || { echo "Missing $path" >&2; exit 1; }
done
# The M10 metapackage must carry the complete battery integration, not merely
# the panel plugin. Check the clean installation including service presets.
for path in usr/libexec/rpd-charger-m10-load usr/lib/systemd/system/rpd-charger-m10.service usr/lib/systemd/system-preset/80-rpd-charger-m10.preset usr/lib/rpd-charger-m10/kernel.json usr/bin/rpd-battery-status usr/libexec/rpd-battery-m10-load usr/libexec/rpd-power-monitor usr/lib/rpd-power/power_model.py usr/share/rpd-power/m10-profiles.json usr/lib/systemd/system/rpd-battery-m10.service usr/lib/systemd/system/rpd-power-monitor.service usr/lib/systemd/system-preset/80-rpd-battery-m10.preset usr/lib/systemd/system-preset/80-rpd-power-monitor.preset; do
    test -f "$root/$path" || { echo "Missing battery integration: $path" >&2; exit 1; }
done
for path in usr/lib/rpd-audio-m10/audio-dtb.py usr/lib/rpd-audio-m10/kernel.json usr/lib/rpd-audio-m10/base.dtb usr/lib/rpd-audio-m10/audio.dtb usr/share/boot-deploy/hooks/95-rpd-audio-m10 usr/share/alsa/ucm2/conf.d/Lenovo-M10/Lenovo-M10.conf usr/share/alsa/ucm2/Lenovo/M10/HiFi.conf etc/wireplumber/wireplumber.conf.d/51-rpd-m10-audio.conf; do
    test -f "$root/$path" || { echo "Missing audio integration: $path" >&2; exit 1; }
done
for module in m10_battery m10_adc5_battery m10_charger m10_audio_pmic m10_wcd_analog m10_speaker_amp; do
    find "$root/usr/lib/modules" -name "$module.ko" | grep -q .
done
for path in usr/lib/rpd-gpu-m10/msm.ko usr/lib/rpd-gpu-m10/ubwc_config.ko usr/lib/rpd-gpu-m10/renderer.sh usr/libexec/rpd-gpu-m10-probe usr/libexec/rpd-gpu-m10-load usr/share/boot-deploy/hooks/96-rpd-gpu-m10; do
    test -f "$root/$path" || { echo "Missing GPU integration: $path" >&2; exit 1; }
done
# No render node exists in the clean test root: verify the actual fallback.
chroot "$root" /bin/sh -ec '. /usr/lib/rpd-gpu-m10/renderer.sh; test "$RPD_SOFTWARE_RENDERING" = 1; test "$WLR_RENDERER" = pixman'
apk --root "$root" info -s > out/installed-sizes.txt
apk --root "$root" info > out/installed-packages.txt
# Alpine and postmarketOS differ in whether /sbin is merged into /usr.
chroot "$root" /bin/sh -c 'command -v lvm' >/dev/null
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
