# RPD APK

Unofficial, minimal port of Raspberry Pi Desktop components to postmarketOS / Alpine edge aarch64. This installs a desktop on the existing OS, not the Debian-based Raspberry Pi OS distribution. No Raspberry board firmware, kernel, boot configuration, GPIO tools or APT integration is included.

Do not treat a successful build as an M10 graphics qualification. The M10 currently exposes simpledrm, not accelerated Adreno rendering.

## Package selection

- `rpd-desktop-lite`: labwc; Raspberry wf-panel-pi, clock, application menu, window list, eject/network/volume/battery plugins and Squeekboard button; Raspberry PCManFM fork; PiXtrix theme/icons; LXTerminal, Mousepad, Xarchiver; NetworkManager GUI, MATE polkit agent, keyring, GVFS/UDisks automount, XDG session services, PipeWire/WirePlumber, portals, XWayland and software-capable Mesa.
- `rpd-desktop-m10`: adds an explicit software-rendered session entry. It selects software rendering for desktop and greeter. LightDM and the Raspberry Pi greeter are configured. Host service presets may enable LightDM during installation (postmarketOS systemd does this). Stop Buffyboard before a graphical trial and verify service enablement before rebooting.
- `rpd-desktop-browser`: optional Firefox, kept outside the smallest installation.
- Buffyboard remains the console keyboard. Squeekboard is the separate Wayland keyboard.

Official Raspberry sources are tracked from the signed Trixie source index. Standard applications and labwc follow Alpine's packaging; they are not replaced by Debian binaries. Hardware plugins (GPU temperature, voltage/power warnings), Raspberry Connect, raspi-config, piwiz, cloning/imaging tools, APT updater and recommended educational suites are excluded. Audio and battery controls use the host services; physical hardware support remains dependent on the M10 kernel. The Raspberry Bluetooth panel plugin and BlueZ are included for mice, keyboards and other peripherals. No browser, office suite or IDE is pulled into the minimal profile.

The portable panel's preferences open its per-user configuration in Mousepad. The Raspberry Control Centre and the legacy GTK2 theme engine are excluded. Launcher edits create a per-user desktop entry and open it in Mousepad. See [desktop integration](docs/DESKTOP.md) for the upstream mapping, service lifecycle and hardware verification limits.

## Local build

Run `scripts/build.sh` as root in a disposable **aarch64 Alpine edge** container. It creates an unprivileged builder and a throwaway build key, compiles individual APKs with abuild, then installs the complete M10 profile into a clean root for dependency/file checks. Output: `out/`.

`upstream.lock.json` pins published tarballs and hashes. `scripts/generate.py` regenerates upstream APKBUILDs; local changes are ordinary patches under each port. Source archives and license notices must be retained with distributed binaries.

Session configuration is in `/etc/xdg/rpd/`. `rpd-session` uses defaults directly so package upgrades update them. A custom `${XDG_CONFIG_HOME:-~/.config}/rpd/labwc` directory overrides compositor configuration; it is never overwritten. Panel customizations use `~/.config/wf-panel-pi/`. APK preserves modified `/etc` files with standard `.apk-new` handling.

## Updates and publication

GitHub Actions checks the signed official Trixie source index daily, selects our explicit component allowlist, validates tarball hashes and rebuilds native ARM64 APKs against Alpine edge. The build job uses a disposable signing key and runs clean-root installation and headless graphical tests. A separate job replaces the test signatures using the dedicated `APK_SIGNING_KEY` Actions secret, checks the production signatures and installation, and publishes with GitHub Pages. The production key is never exposed to upstream build scripts or included in public artifacts. The Mac is not required.

Every run allocates increasing package revisions in Git before building, so `apk upgrade` can install ABI rebuilds. Failed builds leave a skipped revision but do not deploy. Scheduled runs can be delayed or disabled by GitHub's inactivity policy; the Actions page shows their status. The workflow can also be started manually.

This follows *published source packages*, not development commits. Unknown layouts, unsupported version formats, archive changes without version bumps, patch failures and failed tests stop publication. New Raspberry metapackage dependencies do not automatically enter the hardware-independent allowlist. A maintainer must adapt incompatible upstream changes. Headless tests do not qualify physical touch/GPU/display behavior.

Public key: `keys/rpd-apk.rsa.pub`. The private counterpart is held as an encrypted GitHub Actions secret, with a local backup outside Git. Repository write access and workflow changes must therefore be trusted. Actions are pinned to commit IDs. Local builds use a throwaway key by default.

Client updates use `apk update && apk upgrade`. No unattended root upgrades or reboots are enabled on the tablet. Alpine and postmarketOS packages keep their original repositories.

## Client setup (after the first successful Pages deployment)

Repository URL: `https://frenchfaso.github.io/rpd-apk` (APK appends `/aarch64`).
Public-key SHA-256: `fc384ed522d75a810aa1670ed3e52f7f0c3a4f66ff1761e4fd704b937f1f7ed2`.

Review and run `scripts/install-repository.sh` as root on the M10. It verifies
that exact public-key hash and adds the repository once. Then:

```sh
sudo apk add rpd-desktop-m10
# From a local logged-in TTY; first stop Buffyboard for that graphical trial:
rpd-session-m10
# Later package updates:
sudo apk update && sudo apk upgrade
```

Do not launch the compositor over a plain SSH session. A working local logind
session and access to the display/input devices are required. The package does
not configure autologin or stop Buffyboard. Host presets may enable the display
manager automatically; check `systemctl is-enabled lightdm` after installation.
On an M10 with Buffyboard, establish mutual exclusion and console recovery before
enabling normal graphical boot. Exit the desktop to return to the terminal.
