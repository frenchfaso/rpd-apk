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
| galculator, eom, evince, VLC | Same applications from Alpine repositories; VLC uses original Raspberry GTK2/Qt style plugins |
| raindrop, rpinters, rp-bookshelf | Original Screens/Printers modules and Bookshelf |
| rc-gui Localisation | Original dialogs, portable user locale/XKB backend and systemd timedated |
| raspi-ui-overrides | Original menu names, categories and visibility; absent Debian-only MIME targets removed |
| gui-runcmd, gui-screenshot, squeekboard | Original Raspberry Run/Screenshot utilities and Alpine Squeekboard |
| GVFS, UDisks, keyring, polkit, PipeWire, BlueZ, NetworkManager | Host services and upstream Raspberry panel plugins |

Excluded: raspi-config and its unported System/Interfaces/Performance pages, Pi boot/firmware/EEPROM/GPIO/camera tools, V3D GPU telemetry, Pi power warnings, Pi cloning/imaging, Pi Connect, first-boot wizard, APT updater/package manager/recommended software installer. No fake placeholders for these. Generic Wi-Fi, Bluetooth, volume, battery and removable-drive controls remain, subject to host hardware support.

Differences from a complete official Desktop image: browser is the optional `rpd-desktop-browser` profile, so its pinned launcher is omitted in the minimal panel; no IDE/office/education suite. Screens, Printers, keyboard layout, mouse speed/handedness, double click and keyboard repeat settings are included. Localisation retains original dialogs; language is per-user and applies on the next login. Wi-Fi regulatory-country selection requires a host-specific backend and is hidden. The remaining raspi-config System/Interfaces pages have not been presented as working portable settings. Touch Squeekboard activation and console recovery are device integrations. Rendering on M10 remains software-only; matching appearance cannot make its hardware support identical to a Pi.

New Raspberry dependencies require explicit classification; they are not imported blindly. Published compatible source revisions rebuild through the signed repository. LXTask's known two-patch Debian layout is checked during build: changes to that layout require review so Pi GPU code cannot silently enter the portable build.

Validation must include native ARM compilation, clean-root dependency/file-conflict checks, headless classic menu and RPCC startup, accessory startup, and physical M10 panel/menu observation. These are functional checks, not a measured percentage of desktop equivalence.

The official Trixie photographic wallpaper license explicitly forbids redistribution. It is excluded from our APKs and mirrored source archives. Personal installation can retrieve the published archive directly from Raspberry; images must not be committed or republished here.


M10 touch extension: one simultaneous two-finger tap generates a right click at the first contact, without first sending a left click. Contacts must begin within 150 ms, finish within 260 ms and stay within 12 layout pixels. Native touch resumes on motion, a third contact or timeout. A stationary first touch may be delayed up to 260 ms; normal quick taps are delivered on release. This is an opt-in local labwc patch, not a stock Raspberry feature. USB/Bluetooth mouse handling is unchanged. The M10 metapackage pins the tested compositor revision; upgrading labwc itself requires patch review and regression testing. Raspberry application sources continue to track signed upstream releases automatically.

Login appearance and touch/display mapping use an authenticated polkit helper with fixed destinations and validated values. CUPS on a systemd postmarketOS host additionally needs `cups-systemd cups-filters-systemd`; enable the distribution's CUPS socket/service. The UI can discover/configure printers but successful physical printing requires a printer-specific test.

Qt5's original GTK2 platform/style plugin reads the shared GTK settings directly; qt5ct is not available in Alpine edge and is not required for this integration. The original Qt configuration assets remain available for upstream appearance tooling.
