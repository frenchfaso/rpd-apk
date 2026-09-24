#!/bin/sh
# Run as root in a disposable native aarch64 Alpine edge container.
set -eu
# Keep output/key paths stable across abuild releases adopting XDG defaults.
export ABUILD_USERDIR=/home/builder/.abuild
export REPODEST=/home/builder/packages
cd "$(dirname "$0")/.."
[ "$(uname -m)" = aarch64 ] || { echo 'Native aarch64 build required' >&2; exit 1; }
# pmOS installs modules under /usr; Alpine's depmod still reads /lib.
# This alias is confined to the disposable test/build container.
mkdir -p /usr/lib/modules
[ -e /lib/modules ] || ln -s /usr/lib/modules /lib/modules
sh scripts/test-kernel-priority.sh
apk add --no-cache alpine-sdk abuild-rootbld meson samurai python3 git sudo
# Keep shared build dependencies installed between ports.
apk add --no-cache pkgconf gettext-dev gtk+3.0-dev gtkmm3-dev gtk-layer-shell-dev glm-dev wayland-dev wayland-protocols libxml2-dev libinput-dev libevdev-dev eudev-dev libdbusmenu-gtk3-dev menu-cache-dev networkmanager-dev libnma-dev libsecret-dev pulseaudio-dev
python3 tests/verify_charge_status.py ports/rpd-backlight-m10/m10_battery.c
python3 tests/verify_qg_snapshot.py ports/rpd-backlight-m10/m10_battery.c
python3 tests/verify_display_retention.py ports/rpd-backlight-m10/m10_firmware_backlight.c
adduser -D builder 2>/dev/null || true
addgroup builder abuild 2>/dev/null || true
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-builder
mkdir -p /home/builder/.abuild /home/builder/packages
chown -R builder:builder /home/builder/.abuild /home/builder/packages
# A throwaway build key; production signing happens only after validation.
if [ -n "${RPD_SIGNING_KEY:-}" ]; then
    install -m600 "$RPD_SIGNING_KEY" /home/builder/.abuild/rpd-apk.rsa
    cp keys/rpd-apk.rsa.pub /home/builder/.abuild/rpd-apk.rsa.pub
    printf 'PACKAGER_PRIVKEY=/home/builder/.abuild/rpd-apk.rsa\n' > /home/builder/.abuild/abuild.conf
    chown -R builder:builder /home/builder/.abuild
else
    su builder -c 'abuild-keygen -a -i -n'
fi
cp /home/builder/.abuild/*.pub /etc/apk/keys/
mkdir -p /home/builder/rpd-build
cp -a . /home/builder/rpd-build/
chown -R builder:builder /home/builder/rpd-build /home/builder/packages
printf '\n/home/builder/packages/ports\n' >> /etc/apk/repositories
for pkg in rpd-lvm-m10 squeekboard rpd-cpu-topology-m10 rpd-backlight-m10 rpd-settings-backend rpd-autorotate labwc gtk-layer-shell rpd-chromium-defaults rpd-gtk2-engine rpd-qt-gtk2 rpd-theme rpd-icons rpd-menu-data rpd-panel rpd-clock rpd-keyboard-button rpd-window-list rpd-menu rpd-file-manager rpd-ejecter rpd-network rpd-volume rpd-battery rpd-power rpd-shutdown rpd-bluetooth rpd-greeter rpd-task-manager rpd-control-center rpd-appearance rpd-run rpd-screenshot rpd-menu-editor rpd-shortcuts rpd-localisation rpd-input-settings rpd-classic-menu rpd-display-settings rpd-printer-settings rpd-bookshelf rpd-session rpd-login rpd-desktop-lite rpd-desktop-browser rpd-desktop-m10; do
    su builder -c "cd /home/builder/rpd-build/ports/$pkg && abuild -r"
    if [ "$pkg" = rpd-battery ]; then
        su builder -c "cd /home/builder/rpd-build/ports/rpd-battery && abuild fetch unpack prepare"
        python3 tests/verify_battery_sysfs.py /home/builder/rpd-build/ports/rpd-battery/src/pplug-batt
    fi
    if [ "$pkg" = rpd-bookshelf ]; then
        su builder -c "cd /home/builder/rpd-build/ports/rpd-bookshelf && abuild fetch unpack prepare"
        python3 tests/verify_bookshelf_space.py /home/builder/rpd-build/ports/rpd-bookshelf/src/bookshelf/src/rp_bookshelf.c
        python3 tests/verify_bookshelf_cache.py /home/builder/rpd-build/ports/rpd-bookshelf/src/bookshelf/src/rp_bookshelf.c
        python3 tests/verify_bookshelf_batch.py /home/builder/rpd-build/ports/rpd-bookshelf/src/bookshelf/src/rp_bookshelf.c
    fi
    apk update
    if [ "$pkg" = gtk-layer-shell ]; then apk add --upgrade gtk-layer-shell gtk-layer-shell-dev; fi
    # The next plugin needs the panel's exported headers and pkg-config file.
    if [ "$pkg" = rpd-panel ]; then apk add rpd-panel-dev; fi
done
mkdir -p out/aarch64 out/keys
cp /home/builder/packages/ports/aarch64/*.apk out/aarch64/
cp /home/builder/.abuild/*.pub out/keys/
cp /home/builder/packages/ports/aarch64/APKINDEX.tar.gz out/aarch64/
sh scripts/smoke.sh

# Retain exact corresponding upstream sources alongside published GPL binaries.
mkdir -p out/sources
cp /var/cache/distfiles/*.tar.* out/sources/
cp upstream.lock.json out/
