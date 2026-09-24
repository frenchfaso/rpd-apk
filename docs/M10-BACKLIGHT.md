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
issuing commands after a timeout/error. Native DRM takeover and reconstruction
of lost display state are not implemented; the retention workaround below avoids
that loss. Remove this package when a proper native display driver becomes available.

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

## Firmware display retention during suspend

On the verified kernel, s2idle powers off `mdss_gdsc`, clearing DSI configuration.
Simpledrm cannot reconstruct the bootloader state. The backlight bridge now
registers a genpd notifier on the active simple-framebuffer device and vetoes
this domain's power-off through the kernel API. It does not edit domain flags or
program clocks/voltages. Other domains and system suspend remain independent.

Registration checks the qualified board/panel, active simple-framebuffer driver,
powered-on genpd and exact domain name. An existing notifier is never replaced.
If registration fails, brightness still works, but a kernel warning explains
that suspend may lose scanout. Unloading removes the notifier and releases the
framebuffer reference. These APIs require the framebuffer to remain attached;
native DRM takeover while this firmware bridge is loaded is unsupported.

This workaround retains display-domain power and therefore costs energy. It is
not native low-power panel suspend. The opt-in M10 sleep policy below requires
this retention mechanism before requesting suspend. `/sys/module/m10_firmware_backlight/parameters/retention_active`
reports registration; `retained` counts vetoed power-off attempts. Loading the
module with `retain_display=0` opts out.

Without retention, the live DSI CTRL changed from `0x1f3` to zero during s2idle.
With retention, a 30-second RTC test preserved all sampled host registers and
restored brightness without reboot; the user verified the greeter and touch.
The project hardware notes record final packaged-driver checks. Short tests do
not establish sleeping current, long-duration reliability or native-driver
power efficiency. Failure-injection fixtures exercise the actual helpers for
wrong devices/domains, notifier conflicts and balanced cleanup.

The integrated `7.1.3-r27` package also passed a 90-second RTC suspend on battery:
91.3 seconds actually suspended, unchanged sampled DSI registers and restored
brightness without reboot. QG measured about 139 mA across the 91.7-second
measurement interval, including transitions. This is still far above the
hardware rest-reference threshold, and is not a long-term standby benchmark.


## M10 Power key and inactivity policy

The M10 configuration enables guarded s2idle through logind:

- A short Power press suspends; Power wakes the tablet. The wake key release is
  suppressed briefly so it cannot immediately suspend again.
- The existing Screen Blanking setting still blanks the desktop after ten
  minutes of inactivity. Touch or other input wakes this blanked display.
- Automatic suspend after blanking is disabled. The screen stays blank until
  input wakes it; a deliberate Power press can still request s2idle.
- The greeter handles Power and display restoration through the same helper.
  Its existing lack of automatic blanking is unchanged.

In `/etc/xdg/rpd/screen-power.conf`, `power_button_suspend=true` enables manual
s2idle independently of `after_blank_seconds=0`, which disables automatic sleep.
A positive delay would count from the actual blank event. Older configurations
without `power_button_suspend` retain their previous behavior; targets without
this configuration are unchanged.

The helper requires the firmware display-retention module to report active and
`/sys/power/mem_sleep` to contain only `[s2idle]`. Otherwise automatic suspend is
skipped and Power falls back to display toggling. Official kernel upgrades remain
unrestricted, including when the optional module cannot rebuild.

A separate swayidle listener blanks before logind sleep and restores brightness
and scanout after resume, in both user and greeter sessions. Calls to logind happen
outside the brightness-state lock, so its delay-inhibitor callback cannot deadlock.
Normal sleep inhibitors are respected; for example, an active SSH PAM session can
block suspend. A rejected request restores the display. No deep sleep, hibernation,
automatic logout or screen lock is added by this policy.
