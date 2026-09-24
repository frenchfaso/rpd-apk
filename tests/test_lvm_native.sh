#!/bin/sh
# Run as root in a disposable privileged Linux container. Only scratch images
# created here are used; no physical disk or existing volume group is modified.
set -eu
apk add --no-cache lvm2 util-linux e2fsprogs e2fsprogs-extra python3
# Container-private mount: expose nodes created by this VM kernel.
mount -t devtmpfs devtmpfs /dev
work=$(mktemp -d /tmp/rpd-lvm-test.XXXXXX)
vg=rpdtest$$
system_loop= data_loop= mapped=
cleanup() {
    umount "$work/mnt" 2>/dev/null || true
    lvm vgchange -an --config 'devices { use_devicesfile=0 } activation { udev_sync=0 udev_rules=0 monitoring=0 }' "$vg" >/dev/null 2>&1 || true
    [ -z "$mapped" ] || losetup -d "$mapped"
    [ -z "$data_loop" ] || losetup -d "$data_loop"
    [ -z "$system_loop" ] || losetup -d "$system_loop"
    rm -rf "$work"
}
trap cleanup EXIT
truncate -s 96M "$work/system.img"
truncate -s 128M "$work/userdata.img"
printf 'label: dos\nstart=2048,size=32768,type=83\nstart=34816,type=83\n' | sfdisk "$work/userdata.img" >/dev/null
system_loop=$(losetup -f --show "$work/system.img")
data_loop=$(losetup -fP --show "$work/userdata.img")
mkfs.ext2 -q "${data_loop}p1"
mkfs.ext4 -q "${data_loop}p2"
mkdir "$work/mnt"
mount "${data_loop}p1" "$work/mnt"
printf 'boot-is-outside-lvm\n' > "$work/mnt/marker"
umount "$work/mnt"
lvm pvcreate --yes --devices "$system_loop" "$system_loop"
lvm vgcreate --devices "$system_loop" "$vg" "$system_loop"
lvm lvcreate --devices "$system_loop" -l 100%FREE -n root "$vg" --config 'activation { udev_sync=0 udev_rules=0 monitoring=0 }'
mkfs.ext4 -q "/dev/$vg/root"
mount "/dev/$vg/root" "$work/mnt"
printf 'root-survives-extension\n' > "$work/mnt/marker"
umount "$work/mnt"
# Replace only the device-specific config/compatible paths for this fixture;
# all loop, block-device checks and LVM activation commands remain unchanged.
repo=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
export work system_loop vg repo
python3 - <<'PY'
import os
from pathlib import Path
w=Path(os.environ['work'])
(w/'compatible').write_bytes(b'lenovo,tbx505x\0')
s=(Path(os.environ['repo'])/'ports/rpd-lvm-m10/20-rpd-lvm-m10.sh').read_text()
s=s.replace('/etc/rpd-lvm-m10.conf',str(w/'config')).replace('/proc/device-tree/compatible',str(w/'compatible'))
s=s.replace('/dev/disk/by-partuuid/$userdata_partuuid',str(w/'data')).replace('/dev/disk/by-partuuid/$system_partuuid',os.environ['system_loop'])
(w/'hook').write_text(s)
(w/'config').write_text('userdata_partuuid=1111\nsystem_partuuid=2222\nvolume_group='+os.environ['vg']+'\n')
PY
# Add the second PV only after a successful activation from the first PV.
for phase in one two; do
    lvm vgchange -an --devices "$system_loop,${data_loop}p2" "$vg" --config 'activation { udev_sync=0 udev_rules=0 monitoring=0 }'
    losetup -d "$data_loop"
    data_loop=$(losetup -fP --show "$work/userdata.img")
    ln -sf "$data_loop" "$work/data"
    # The hook associates an outer loop with its backing block device, as on M10.
    # Here that creates a second loop over the file-backed outer device.
    sh "$work/hook"
    mapped=$(losetup -j "$data_loop" --noheadings --output NAME)
    test -n "$mapped"
    sh "$work/hook"
    test "$(losetup -j "$data_loop" --noheadings --output NAME | wc -l)" = 1
    mount "/dev/$vg/root" "$work/mnt"
    test "$(cat "$work/mnt/marker")" = root-survives-extension
    umount "$work/mnt"
    mount "${mapped}p1" "$work/mnt"
    test "$(cat "$work/mnt/marker")" = boot-is-outside-lvm
    umount "$work/mnt"
    if [ "$phase" = one ]; then
        lvm pvcreate --yes --devices "$system_loop,${mapped}p2" "${mapped}p2"
        lvm vgextend --devices "$system_loop,${mapped}p2" "$vg" "${mapped}p2"
        lvm lvextend --devices "$system_loop,${mapped}p2" -l +100%FREE "/dev/$vg/root" --config 'activation { udev_sync=0 udev_rules=0 monitoring=0 }'
        e2fsck -pf "/dev/$vg/root"
        resize2fs "/dev/$vg/root"
    fi
    lvm vgchange -an --devices "$system_loop,${mapped}p2" "$vg" --config 'activation { udev_sync=0 udev_rules=0 monitoring=0 }'
    losetup -d "$mapped"
    mapped=
done
printf 'PASS: real LVM one/two-PV activation, remapping, idempotence, boot isolation and filesystem growth\n'
