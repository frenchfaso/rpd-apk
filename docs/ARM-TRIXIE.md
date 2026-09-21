# ARM Trixie desktop reference

Reference: RPi-Distro/pi-gen `arm64`, stage3/00-install-packages and stage4/00-install-packages; signed Raspberry Trixie Sources; rpd-metas 1.30. This is not the Debian 11 x86 Raspberry Pi Desktop product. `rpd-desktop-lite` means our minimal graphical profile: official Raspberry Pi OS **Lite has no desktop**.

The package mapping deliberately follows the desktop packages rather than copying the full image's development, education and office software.

| Official component | Portable implementation |
| --- | --- |
| labwc + wf-panel-pi | Same compositor/panel; official smenu, launchers and window-list layout |
| PiXtrix + Nunito Sans | Same theme, icon set and font family; neutral wallpaper default |
| pi-greeter + LightDM | Same greeter/manager, portable PAM/session integration and Squeekboard |
| rpcc, pipanel, merp, pished, rasputin | Same Control Centre, appearance/panel, menu editor, shortcut editor, mouse/keyboard module |
| pcmanfm-pi, lxterminal, mousepad, xarchiver | Raspberry file-manager fork; Alpine packages for the standard applications |
| lxtask | Official signed Raspberry source plus GTK3 patch, omitting V3D-only gpustats.patch |
| galculator, eom, evince | Same applications from Alpine repositories |
| gui-runcmd, gui-screenshot, squeekboard | Original Raspberry Run/Screenshot utilities and Alpine Squeekboard |
| GVFS, UDisks, keyring, polkit, PipeWire, BlueZ, NetworkManager | Host services and upstream Raspberry panel plugins |

Excluded: raspi-config/rc-gui, Pi boot/firmware/EEPROM/GPIO/camera tools, V3D GPU telemetry, Pi power warnings, Pi cloning/imaging, Pi Connect, first-boot wizard, APT updater/package manager/recommended software installer. No fake placeholders for these. Generic Wi-Fi, Bluetooth, volume, battery and removable-drive controls remain, subject to host hardware support.

Differences from a complete official Desktop image: browser is the optional `rpd-desktop-browser` profile, so its pinned launcher is omitted in the minimal panel; no IDE/office/education suite. Display/printer configuration and the raspi-config-backed keyboard-layout page are not ported. Mouse speed/handedness, double click and keyboard repeat settings are included. Touch Squeekboard activation and console recovery are device integrations. Rendering on M10 remains software-only; matching appearance cannot make its hardware support identical to a Pi.

New Raspberry dependencies require explicit classification; they are not imported blindly. Published compatible source revisions rebuild through the signed repository. LXTask's known two-patch Debian layout is checked during build: changes to that layout require review so Pi GPU code cannot silently enter the portable build.

Validation must include native ARM compilation, clean-root dependency/file-conflict checks, headless classic menu and RPCC startup, accessory startup, and physical M10 panel/menu observation. These are functional checks, not a measured percentage of desktop equivalence.

The official Trixie photographic wallpaper license explicitly forbids redistribution. It is excluded from our APKs and mirrored source archives. Personal installation can retrieve the published archive directly from Raspberry; images must not be committed or republished here.
