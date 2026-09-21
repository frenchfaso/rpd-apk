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
refuses other kernel versions. The repository rebuilds the module for a new kernel before allowing the
matched APK upgrade, as described below; unsupported running kernels are refused. Do not copy this binary into another kernel's directory.

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

## Kernel update contract

The backlight APK depends on the **exact official kernel APK version**, including
its `-rN` revision. Kernel source, `/boot/config` from the signature-verified
published APK, and the matching LLVM major version are used to build the module.
Only the native userspace-link capability (`CONFIG_CC_CAN_LINK`) may differ; all
other configuration changes stop the build. Export resolution must pass.

The scheduled repository workflow checks the signed postmarketOS kernel package
with `scripts/update-m10-kernel.py`. For a new kernel it checks the reviewed
upstream recipe, updates the source checksum and exact kernel dependency, and
builds a new module before signing/publishing. Changes to the recipe beyond
version/checksums require review. The code never executes the downloaded recipe.

If preparation/build/signing fails, the previous repository remains published.
Its exact dependency prevents an ordinary APK upgrade from selecting a newer,
unmatched kernel. APK may retain the old pair or report a dependency conflict;
this is intentional and **can delay kernel security updates**, so failed builds
need attention. It is not a promise that arbitrary future kernels work without
maintenance. CI compilation cannot replace a physical regression test on M10.

Do not remove the backlight dependency or force a kernel upgrade around it. An
upgrade installs the matched pair; the new kernel/module are used after reboot.
The loader checks the running kernel and refuses a module for another release.
No compiler, kernel source tree, or build workload is required on the tablet.

Validated on 2026-09-22: the module loads on the stock 7.1.3-msm89x7 kernel;
its module structure is 0x500 bytes, matching a distributed kernel module.
Unprivileged brightnessctl writes to 64 and back to 32 succeeded. The video-group
udev permissions and systemd-backlight load service are active. The isolated APK
solver test retains an installed old pair even after the old kernel disappears
from the repository, then upgrades both when the matching module is available.
The APK is installed on M10 with its service enabled. Saving 64, unloading and
reloading the packaged module restored 64 successfully; the level was then
returned to 32. The temporary test signing key was used only for that transaction
and was not added to the device trust store. A full reboot remains untested.
