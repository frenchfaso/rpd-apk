# Optional M10 LVM root

`rpd-lvm-m10` provides early-boot activation for a manually configured M10 LVM
root. Installing the desktop or this package never formats, converts or resizes
storage. Existing installations continue to boot normally without a configuration.

The intended layout keeps the original outer GPT, firmware partitions and
nested `/boot`. LVM combines the old Android `system` partition with the second
nested partition inside `userdata`; a single ext4 root provides their combined
space. `/boot` must remain outside LVM so lk2nd can load kernel and initramfs.

A root-owned `/etc/rpd-lvm-m10.conf` supplies the actual GPT identifiers:

```sh
userdata_partuuid=YOUR_USERDATA_PARTUUID
system_partuuid=YOUR_SYSTEM_PARTUUID
volume_group=m10linux
```

These values are installation-specific. The hook validates the board, maps the
nested partitions and requires complete VG activation before normal pmOS root
mounting. Use the root filesystem UUID in `/etc/fstab`; standard boot-deploy
propagates it to extlinux. Run `mkinitfs` after changing the configuration.
The package participates in normal initramfs regeneration on kernel upgrades.
Only the M10's merged initramfs layout is targeted.

Migration requires copying the existing system to a new filesystem and testing
its boot before reusing the old root area. Adding the package alone does not
perform this migration. A fresh stock recovery/factory reset or flashing Android
system/userdata will overwrite LVM data.

Qualification: host guard tests are provided in the port. The privileged
`tests/test_lvm_native.sh` uses disposable disk images in an isolated Linux
container to verify activation, loop remapping and filesystem expansion.
On 2026-09-24, TB-X505L with kernel 7.1.3-msm89x7 passed a real one-PV boot,
online extension to two PVs, APK-triggered initramfs regeneration and a second
boot. The 25.49 GiB LV provides about 25.0 GiB of ext4 space. The outer GPT and
nested boot partition were unchanged; Wi-Fi, graphical login and desktop worked.
This verifies the update mechanism with the current kernel, not every future
kernel version.
