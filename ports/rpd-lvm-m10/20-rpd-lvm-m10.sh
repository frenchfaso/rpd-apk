#!/bin/sh
# Activate an explicitly configured M10 root; never create or resize storage.
set -eu
config=/etc/rpd-lvm-m10.conf
[ -r "$config" ] || exit 0
tr '\000' '\n' < /proc/device-tree/compatible | grep -qx 'lenovo,tbx505x' || exit 0
. "$config"
case "$userdata_partuuid:$system_partuuid" in
    *[!a-fA-F0-9:-]*|:*) echo 'Invalid LVM partition identifiers' >&2; exit 1;;
esac
[ -n "$userdata_partuuid" ] && [ -n "$system_partuuid" ]
case "$volume_group" in ''|*[!a-zA-Z0-9_]*) echo 'Invalid LVM group' >&2; exit 1;; esac
userdata=/dev/disk/by-partuuid/$userdata_partuuid
system=/dev/disk/by-partuuid/$system_partuuid
for attempt in $(seq 1 30); do
    [ -b "$userdata" ] && [ -b "$system" ] && break
    sleep 1
done
[ -b "$userdata" ] && [ -b "$system" ]
# Current M10 kernels build these in; also accept future modular builds.
modprobe loop 2>/dev/null || true
modprobe dm-mod 2>/dev/null || true
userdata=$(readlink -f "$userdata")
system=$(readlink -f "$system")
# Map the original nested boot/PV pair before the generic pmOS root scan.
# Reuse its loop device on retries, so a PV cannot appear twice.
loop=$(losetup --associated "$userdata" --noheadings --output NAME)
if [ -z "$loop" ]; then
    loop=$(losetup --find --show --partscan --direct-io=on "$userdata")
fi
case "$loop" in /dev/loop*[!0-9]*) echo 'Ambiguous loop mapping' >&2; exit 1;; /dev/loop[0-9]*) ;; *) exit 1;; esac
for attempt in $(seq 1 30); do
    [ -b "${loop}p1" ] && [ -b "${loop}p2" ] && break
    sleep 1
done
[ -b "${loop}p1" ] && [ -b "${loop}p2" ]
# The early udev rules need not contain LVM's autoactivation machinery.
# LVM creates its nodes synchronously and requires every PV in the VG.
lvm vgchange --activate y --activationmode complete --sysinit \
    --devices "$system,${loop}p2" \
    --config 'devices { use_devicesfile=0 } activation { monitoring=0 udev_sync=0 udev_rules=0 }' \
    "$volume_group"
