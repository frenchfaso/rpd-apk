# M10 INX JD9365 backlight

`rpd-backlight-m10` adds a firmware-handoff DSI backlight module for the verified
Lenovo TB-X505L INX JD9365 800p panel and kernel **7.1.3-msm89x7**. It is included
in the M10 desktop profile, but requires explicit per-device activation after
confirming the panel. It must not be enabled on other panel variants by model
name alone.

The module exposes `/sys/class/backlight/m10_backlight` (0..255) and the
`display_name` attribute used by Raspberry Pi's **Screen Configuration** app
(raindrop). The app's display context menu then offers **Brightness**. Standard
brightnessctl udev rules grant the existing video group access; systemd-backlight
can save and restore the level. The user's desktop account must belong to video.

After qualification on this exact panel:

```sh
sudo install -D -m644 /dev/null /etc/rpd/m10-backlight-enabled
sudo systemctl enable --now rpd-backlight-m10.service
brightnessctl -d m10_backlight set 20%
```

The default is 32/255 until systemd restores a saved value. Zero extinguishes
the backlight; an SSH connection can restore it with brightnessctl. The loader
refuses other kernel versions. Kernel upgrades are independent of this module; unsupported kernels skip
backlight loading and retain firmware brightness. Do not copy this binary into another kernel's directory.

This is a narrowly scoped experimental bridge, not native DRM display support.
It retains bootloader scanout and does not initialize PHY/PLL, clocks, panel
power or video timings. It requires the observed firmware register state and
exclusive ownership of the DSI register range, serializes requests, and stops
issuing commands after a timeout/error. Native DRM takeover and suspend/resume
are not implemented. Remove this package when a proper native display driver
becomes available.

Builds use the pinned msm89x7 kernel source and target config, generate actual
vmlinux export metadata, and reject unresolved module imports. APK signatures
verify distribution of the binary; they do not make this an upstream kernel
module. Runtime tests and physical acceptance are documented in the project.

## Kernel updates take priority

User decision, 2026-09-22: never delay an official kernel update for this optional
backlight bridge. The APK has **no kernel dependency or version pin**. Its
`_kernel_apk_version` field records build provenance only. Normal `apk upgrade`
can install a newer kernel even when no matching backlight module exists yet.

At startup the loader checks the running kernel release and the installed kernel
APK revision against its build provenance. If either differs, it logs a skip and
returns successfully without loading the module. A module rejected by the kernel
also leaves boot/session startup running. In that case software brightness control
is unavailable until a compatible backlight package is published; display scanout
continues at the brightness established by the firmware.

The scheduled workflow still checks the authenticated published postmarketOS
kernel, updates the matching source/config/LLVM metadata and rebuilds the module.
Source recipe changes beyond versions/checksums require review. Failed module
builds do not constrain the tablet's official kernel upgrades. Hardware regression
tests remain necessary for new kernels. No compiler is installed on the tablet.

Validation: the module loads on stock 7.1.3-msm89x7, user brightness changes work,
and systemd saves/restores the level across module reload. The 2026-09-22 device
reboot also started the backlight service successfully. The isolated APK solver
test now verifies that a newer kernel installs while the old backlight package
remains installed, and that the backlight can be upgraded separately afterward.

Autorotation is started explicitly by the session supervisor after the Wayland
activation environment is imported; it no longer depends on lxsession filtering
an OnlyShowIn=labwc XDG autostart entry.
