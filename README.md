# RPD APK

Unofficial, minimal port of Raspberry Pi Desktop components to postmarketOS / Alpine edge aarch64. This installs a desktop on the existing OS, not the Debian-based Raspberry Pi OS distribution. No Raspberry board firmware, kernel, boot configuration, GPIO tools or APT integration is included.

Initial packages are under construction; do not treat a successful build as an M10 graphics qualification. The M10 currently exposes simpledrm, not accelerated Adreno rendering.

## Package selection

- `rpd-desktop-lite`: labwc; Raspberry wf-panel-pi, clock, application menu, window list and Squeekboard button; Raspberry PCManFM fork; PiXtrix theme/icons; LXTerminal, Mousepad, Xarchiver; NetworkManager GUI, polkit agent, GVFS, XWayland and software-capable Mesa.
- `rpd-desktop-m10`: adds an explicit software-rendered session entry. It does not replace the device kernel, modify boot or enable a display manager.
- `rpd-desktop-browser`: optional Firefox, kept outside the smallest installation.
- Buffyboard remains the console keyboard. Squeekboard is the separate Wayland keyboard.

Official Raspberry sources are tracked from the signed Trixie source index. Standard applications and labwc follow Alpine's packaging; they are not replaced by Debian binaries. Hardware plugins (GPU temperature, voltage/power warnings), Raspberry Connect, raspi-config, piwiz, cloning/imaging tools, APT updater and recommended educational suites are excluded. Audio/Bluetooth controls are excluded from the minimal profile because those devices are not qualified on M10. No browser, office suite or IDE is pulled into the minimal profile.

The portable panel's preferences open its per-user configuration in Mousepad. The Raspberry Control Centre is excluded. The menu editor uses Alpine's Alacarte. Upstream panel/keyboard/menu rendering needs graphical testing after package build.

## Local build

Run `scripts/build.sh` as root in a disposable **aarch64 Alpine edge** container. It creates an unprivileged builder and a throwaway build key, compiles individual APKs with abuild, then installs the complete M10 profile into a clean root for dependency/file checks. Output: `out/`.

`upstream.lock.json` pins published tarballs and hashes. `scripts/generate.py` regenerates upstream APKBUILDs; local changes are ordinary patches under each port. Source archives and license notices must be retained with distributed binaries.

Session configuration is in `/etc/xdg/rpd/`. `rpd-session` uses defaults directly so package upgrades update them. A custom `${XDG_CONFIG_HOME:-~/.config}/rpd/labwc` directory overrides compositor configuration; it is never overwritten. Panel customizations use `~/.config/wf-panel-pi/`. APK preserves modified `/etc` files with standard `.apk-new` handling.
