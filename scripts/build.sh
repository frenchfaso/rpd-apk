#!/bin/sh
# Run as root in a disposable native aarch64 Alpine edge container.
set -eu
cd "$(dirname "$0")/.."
[ "$(uname -m)" = aarch64 ] || { echo 'Native aarch64 build required' >&2; exit 1; }
apk add --no-cache alpine-sdk abuild-rootbld meson samurai python3 git sudo
# Keep shared build dependencies installed between ports.
apk add --no-cache pkgconf gettext-dev gtk+3.0-dev gtkmm3-dev gtk-layer-shell-dev glm-dev wayland-dev wayland-protocols libxml2-dev libinput-dev libevdev-dev eudev-dev libdbusmenu-gtk3-dev menu-cache-dev networkmanager-dev libnma-dev libsecret-dev pulseaudio-dev
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
for pkg in gtk-layer-shell rpd-theme rpd-icons rpd-menu-data rpd-panel rpd-clock rpd-keyboard-button rpd-window-list rpd-menu rpd-file-manager rpd-ejecter rpd-network rpd-volume rpd-battery rpd-shutdown rpd-bluetooth rpd-greeter rpd-task-manager rpd-control-center rpd-appearance rpd-run rpd-screenshot rpd-menu-editor rpd-shortcuts rpd-input-settings rpd-classic-menu rpd-session rpd-login rpd-desktop-lite rpd-desktop-m10 rpd-desktop-browser; do
    su builder -c "cd /home/builder/rpd-build/ports/$pkg && abuild -r"
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
