# Desktop integration and upstream alignment

The reference is the published `rpd-metas` Trixie source, especially `rpd-common`
and `rpd-wayland-core`. This is an Alpine/postmarketOS port, not Debian packages
installed with APK. The lock tracks published Raspberry archives, never Git HEAD.

| Desktop function | Raspberry Pi OS components retained | Alpine/postmarketOS integration |
|---|---|---|
| Compositor, panel, task list, menu | labwc, wf-panel-pi, pplug-menu (smenu), built-in launchers/window-list | Native Alpine labwc; Raspberry plugins built for musl |
| File manager, desktop, trash | pcmanfm-pi, GVFS, gvfs-fuse | Trash backend and desktop managed by PCManFM; no root file manager |
| User folders | XDG user directories | `xdg-user-dirs-update` at session start; respects locale and user configuration |
| USB storage | PCManFM automount, GVFS/UDisks, pplug-ejecter | `udisks2`, polkit; mount on insertion and session start, autorun disabled |
| Other volumes | GVFS backends | MTP, cameras, SMB, NFS, WebDAV; FAT/exFAT/NTFS tools |
| Network | NetworkManager, pplug-netman | Uses existing system service and secret agent; Alpine libnma network-creation dialog replaces Raspberry-only API |
| Authentication | mate-polkit, gnome-keyring, PAM support | MATE agent in session; keyring/Secret Service via D-Bus; existing login PAM determines automatic unlocking |
| Audio | PipeWire, pipewire-pulse, WirePlumber, pplug-volumepulse | Existing systemd user manager; supervised processes on non-systemd hosts |
| Battery | pplug-batt | Reads kernel power-supply data; cannot add missing M10 battery-driver support |
| Login manager | LightDM, pi-greeter | Original Raspberry greeter built on Alpine; labwc Wayland greeter session with Squeekboard; M10 software rendering |
| Mouse and Bluetooth | libinput, BlueZ, pplug-bluetooth | Touch and USB/Bluetooth mouse coexist; hardware pairing remains to be tested |
| Keyboard | Squeekboard, wfplug-squeek | Wayland on-screen keyboard; Buffyboard remains for console use |
| Session startup | lxsession-xdg-autostart, xsettingsd | Same XDG runner as Raspberry; per-user desktop-entry overrides supported |
| Session services | D-Bus, logind | Import graphical environment; `rpd-session.target` binds to `graphical-session.target`; systemd scopes autostart children |
| Files/dialogs/screen sharing | Standard desktop portals | GTK and wlroots portal backends, D-Bus activated |
| End session | pishutdown | Original dialog; power/reboot use login1 with polkit, logout exits labwc |
| Appearance | PiXtrix GTK/Openbox theme and icons | GTK3 and XSettings; icon/cursor preferences initialised once, later customisations preserved |
| Display/idle tools | kanshi, swayidle, wlopm, swaylock | kanshi starts when a user config exists; no untested automatic suspend/lock policy |

## Deliberate differences

- No Raspberry firmware/kernel, boot options, GPIO tools, Pi voltage/temperature
  plugins, raspi-config, first-boot wizard, imaging/cloning utilities, Connect,
  APT updater or Pi-specific control-centre modules.
- Native RPCC modules provide appearance, panel, menu, shortcuts and mouse/keyboard preferences. See [ARM Trixie mapping](ARM-TRIXIE.md) for exclusions.
- The file manager starts with a plain background; large wallpaper collections,
  browser, office and education suites are outside the minimal profile.
- Chromium is provided by `rpd-desktop-browser`, included on M10, with portable official ARM browser defaults.
- The battery and audio plugins are included as desktop services, but physical
  battery reporting and audio still require working kernel/board support.
- As in the upstream shutdown dialog, screen locking is offered only when a
  hardware keyboard is detected. Squeekboard is not a secure lock-screen keyboard.
- LightDM with the Raspberry Pi greeter is installed/configured; host presets may enable it automatically; no autologin is configured. A local logind login provides seat
  permissions; a plain SSH shell is insufficient to qualify display/automount.

## Storage and session lifecycle

Mount/unmount permissions use standard UDisks/polkit active-local-session policy;
there is no blanket passwordless polkit rule. Alpine automatically selects
`*-systemd` integration subpackages when systemd and their base package are present.
D-Bus activates UDisks and GVFS as needed. Selecting eject in the panel or file
manager unmounts/ejects before physically disconnecting a drive.

PostmarketOS may replace its PulseAudio backend with its PipeWire backend when
installing this profile, matching modern Raspberry Pi OS. APK simulation on the
M10 resolves that transition; the profile does not modify audio kernel drivers.

GNOME Keyring is available, but the first keyring may need to be created/unlocked
in the graphical session. Automatic unlock depends on the host's PAM login stack;
we do not replace an existing PAM configuration or store the login password.

## Validation boundaries

CI compiles native ARM64 APKs, installs into a clean root, then launches a headless
Wayland session. It checks that real compositor/panel/file-manager/keyboard
processes remain alive, runs an XDG autostart probe, checks standard user folders,
and exercises GIO trash and empty-trash on a disposable file. The file-manager
window is captured for inspection. Production signatures are verified again in a
separate container which never trusts the disposable build key.

These tests do not prove physical USB OTG, touch gestures, suspend/resume, audio,
Wi-Fi credentials UI or actual removable-drive mounting on M10. Those require an
on-device session and suitable USB adapter/media. Host USB hardware is not exposed
to CI. CI disables nested Glycin sandboxing only inside its disposable container;
the installed session retains the normal image-loader sandbox.

## Login manager and input

`rpd-login` configures Alpine LightDM with the published Raspberry `pi-greeter`
1.3, running in its own labwc Wayland session and private D-Bus session.
Squeekboard is started there as well as in the user desktop. Raspberry display
connector names and Pi-specific touch device mappings are omitted. Libinput
handles touch and external pointers together; no touchscreen is disabled when a
mouse is attached. The M10 reports a Bluetooth `hci0` controller, but pairing and
input events from a physical Bluetooth mouse are not yet tested.

The greeter configuration uses password login, with no stored password or
automatic login. Authentication and automatic keyring unlock use LightDM's
distribution PAM stack. CI starts real LightDM in an isolated headless test, checks its greeter handshake,
PAM password prompt and visible Squeekboard;
physical login, keyboard entry and the return from logout require device testing.
Before enabling LightDM at boot, perform one reversible on-device trial with SSH
available and the Buffyboard console retained as recovery. BlueZ should be
enabled through the host service manager during that deployment.

Squeekboard comes from Alpine (the same keyboard project used by Raspberry Pi
OS); the panel toggle is Raspberry's published `wfplug-squeek`. The greeter opens
the keyboard when the password field is tapped/clicked and also has an explicit
keyboard button. This
small portability patch avoids depending on Raspberry-only keyboard helpers.
Buffyboard is retained for text-console recovery, not used inside Wayland.

On-device installation confirmed that postmarketOS systemd presets automatically
enable newly installed LightDM, BlueZ and UDisks2 units. This happens in the host's
package trigger even though RPD APKs contain no service-enabling script. Check
enablement before rebooting; stop Buffyboard for graphics and arrange a console
recovery path when configuring permanent graphical boot.

## Alpine GTK touch compatibility

Alpine GTK 3.24.52 includes GNOME MR 5628, adding `last_touch_down_serial` inside
GdkWaylandSeat. Upstream gtk-layer-shell 0.10.1 assumes unpatched GTK: after a
touch it reads this serial as the tablet-list pointer and crashes popup menus.
This repository carries gtk-layer-shell 0.10.1-r100+ with the matching private
layout and completed-touch serial handling. The package build explicitly checks
GTK 3.24.52; an Alpine GTK version change requires reviewing this adaptation.
Official newer gtk-layer-shell releases should replace this compatibility build
once they account for the Alpine patch. It is not a GPU or Wi-Fi driver patch.

CI compares the expected seat size with the independently built GTK runtime and
reproduces the completed-touch serial from the M10 crash. The probe segfaulted
with the original library and passes with the compatibility build. It is shipped
separately in gtk-layer-shell-rpd-test, not in the desktop profile.

On systemd, rpd-panel.service restarts the panel after an unexpected exit (with a
bounded retry limit) and stops with the graphical session. PipeWire XDG autostart
is hidden because the session already starts the audio services, preventing a
second daemon from competing for the same socket.


## Additional original preferences and accessories

The profile includes raindrop (Screens), rpinters (Printers), Bookshelf, the rc-gui Localisation dialogs, and VLC. The original `raspi-ui-overrides` application directory takes precedence in `XDG_DATA_DIRS`, preserving the official names, categories and hidden entries. A duplicate local network launcher and unrelated LXSession preferences are hidden/removed. The supported input-layout button is restored.

The locale backend records a per-user LANG value for the next login; keyboard layouts/variants/options are validated against current XKB data and applied to labwc and Squeekboard. Timezone changes use systemd timedated and its polkit authentication, or the constrained polkit helper on OpenRC. Original locale and keyboard selection data are generated from Alpine's locale/XKB/ISO databases during the build. Unsupported Pi configuration pages and the board-specific Wi-Fi country setter are not exposed.

Display output profiles use a session-scoped kanshi service. Login-screen changes use a constrained, authenticated polkit helper which accepts only font/theme values, output geometry and touch mapping. Arbitrary commands, root destination paths and the rest of user XML are never imported.

VLC uses Raspberry's published GTK2 engine and Qt GTK2 style/platform plugin, sharing the GTK settings. Chromium is now included by the M10 profile. On postmarketOS systemd install `cups-systemd cups-filters-systemd`, start the CUPS socket, and grant a printer administrator appropriate `lpadmin` membership. Printer hardware, Bluetooth/USB mouse and physical gesture tests are distinct from headless build validation.

## Desktop audio policy

The session installs `90-rpd-desktop-audio.conf` under its XDG_CONFIG_DIRS, disabling postmarketOS mobile role loopbacks only in this desktop session. Streams use WirePlumber's standard selected-output routing. On M10, VLC was waiting indefinitely for activation of the Multimedia role loopback despite connected A2DP headphones. Direct routing produced active stereo links to the Bluetooth sink; native pw-play and VLC with repeat disabled completed the four-second WAV. The user's repeat preference is not changed. Physical audibility confirmation remains separate.

Configuration lookup: https://pipewire.pages.freedesktop.org/wireplumber/daemon/locations.html

## M10 login screen

LightDM's private labwc session starts `rpd-autorotate --greeter` when the target
rotation configuration is installed. It claims SensorProxy only for its active,
local greeter session and exits with the greeter process group at login. A private
copy of the compositor configuration under XDG_RUNTIME_DIR lets it set the same
Goodix output mapping as the desktop without making /etc writable to LightDM.

The greeter keyboard follows portrait orientation. Landscape disables the screen
keyboard setting and hides Squeekboard; the password-entry/manual keyboard action
also checks monitor geometry on this profile. Other targets retain the ordinary
manual keyboard behavior. Raspberry's RPiSystem wallpaper, user logo, PiXtrix theme
and Nunito font are used from the pinned ARM packages. Artwork is installed from
rpd-metas, with its BSD-3-Clause copyright, and follows the existing upstream
release tracker.

Verified on the M10: login screen portrait/landscape rotation, aligned touch,
keyboard visible only in portrait (including password-field taps in landscape),
and original wallpaper. The user confirmed the combined result.
