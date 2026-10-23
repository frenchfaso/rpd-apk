#!/bin/sh
# Run only in a disposable native ARM64 Alpine container.
set -eu
[ "$(uname -m)" = aarch64 ]
export ABUILD_USERDIR=/home/builder/.abuild
export REPODEST=/home/builder/packages
apk add --no-cache alpine-sdk python3 git sudo curl
adduser -D builder
addgroup builder abuild
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-builder
mkdir -p /home/builder/.abuild /home/builder/packages /home/builder/rpd-qt6-preflight
install -m644 scripts/source-download.curlrc /home/builder/.curlrc
cp -a . /home/builder/rpd-qt6-preflight/
chown -R builder:builder /home/builder
su builder -c 'abuild-keygen -a -i -n'
cp /home/builder/.abuild/*.pub /etc/apk/keys/
printf '\n/home/builder/packages/ports\n' >> /etc/apk/repositories
for pkg in rpd-gtk2-engine rpd-qt6-gtk2 rpd-theme; do
    su builder -c "cd /home/builder/rpd-qt6-preflight/ports/$pkg && abuild -r"
    apk update
done
apk add rpd-qt6-gtk2 rpd-theme qt6-qtbase-dev xvfb-run dbus font-dejavu
c++ -std=c++17 $(pkg-config --cflags Qt6Widgets) scripts/qt6-theme-probe.cpp -o /tmp/rpd-qt6-probe $(pkg-config --libs Qt6Widgets)
printf 'gtk-theme-name="PiXtrix"\n' > /tmp/rpd-qt6-gtkrc
su builder -c 'dbus-run-session -- xvfb-run -a env QT_QPA_PLATFORM=xcb QT_QPA_PLATFORMTHEME=gtk2 GTK2_RC_FILES=/tmp/rpd-qt6-gtkrc /tmp/rpd-qt6-probe'
