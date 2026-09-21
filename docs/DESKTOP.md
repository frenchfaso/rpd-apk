# Desktop integration and upstream alignment

The reference is the published `rpd-metas` Trixie source, especially `rpd-common`
and `rpd-wayland-core`. This is an Alpine/postmarketOS port, not Debian packages
installed with APK. The lock tracks published Raspberry archives, never Git HEAD.

| Desktop function | Raspberry Pi OS components retained | Alpine/postmarketOS integration |
|---|---|---|
| Compositor, panel, task list, menu | labwc, wf-panel-pi, wfplug-wlist, wfplug-imenu | Native Alpine labwc; Raspberry plugins built for musl |
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
  APT updater or Pi-specific control centre.
- The portable panel preferences edit its user INI in Mousepad. Desktop
  preferences use PCManFM's own dialog. Launcher editing makes a user copy.
- The file manager starts with a plain background; large wallpaper collections,
  browser, office and education suites are outside the minimal profile.
- Firefox is the separate `rpd-desktop-browser` metapackage.
- The battery and audio plugins are included as desktop services, but physical
  battery reporting and audio still require working kernel/board support.
- As in the upstream shutdown dialog, screen locking is offered only when a
  hardware keyboard is detected. Squeekboard is not a secure lock-screen keyboard.
- LightDM with the Raspberry Pi greeter is installed/configured but not enabled automatically; no autologin is configured. A local logind login provides seat
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
