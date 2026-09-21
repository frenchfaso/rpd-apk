# ARM Trixie desktop alignment

Reference: published Raspberry Pi OS Trixie ARM packages, including rpd-metas 1.31 and rpi-chromium-mods 20260211. Raspberry Pi OS Lite itself has no graphical desktop; this project supplies a minimal graphical profile, not the complete Debian image.

## Included integrations

- Original RPCC System, Display and Interfaces widgets now expose password, hostname, graphical/console boot, desktop autologin, installed browser selection, screen blanking, SSH and VNC. Pi firmware, buses, serial settings, splash/LED and hardware-only controls remain hidden. Localisation remains the original module with Alpine data.
- Host changes use a fixed-operation polkit helper. Passwords arrive on stdin, never shell arguments. Authentication is required; only the calling regular account can have its password or autologin changed. No blanket passwordless administration policy is installed.
- `sudo rpd-configure-host USER` explicitly configures LightDM, network, Bluetooth and existing basic CUPS services for systemd or OpenRC. It grants printer administration to that account. It preserves the M10 console recovery configuration and does not enable autologin.
- Screen blanking is opt-in: swayidle turns outputs off after ten minutes, wlopm restores them on activity. It does not suspend or lock. The session supervises its children.
- VNC is opt-in and binds only to 127.0.0.1:5900. Enable SSH and use `ssh -L 5900:127.0.0.1:5900 frenchfaso@M10.local`, then connect a VNC viewer to localhost:5900. No public unauthenticated listener or stored VNC password is created. Both VNC and blanking start disabled.
- Screens identifies touchscreens through udev metadata, without raw input-device permissions.
- Packaged MIME cache repairs the original Raspberry application overrides: file manager, images, PDF, video and archives resolve to their installed applications.
- ZIP/7z creation/extraction, English spelling dictionary, FFmpeg/GStreamer codecs and Windows share discovery complement the existing accessories, VLC, GVFS and removable-media stack.

## Chromium

The M10 profile now installs native Alpine Chromium. HTTP, HTTPS, HTML and XHTML default to Chromium. A once-per-user migration adds the browser launcher while preserving existing panel choices; later customisations are not overwritten. Installing Firefox separately makes it selectable in Control Centre.

`rpd-chromium-defaults` tracks the signed official ARM source of `rpi-chromium-mods`. It packages the original bookmarks and initial preferences, including system theme and the original first-run page, with the bookmarks path adapted to Alpine. Recommended policies select DuckDuckGo, disable search suggestions and show the bookmarks bar; users can override recommended settings. Initial preferences apply to newly created profiles, not existing user profiles.

The unbranded Chromium first-run dialog is suppressed because it displays an empty terms placeholder; first-run preferences and bookmark import remain enabled. Only portable data is retained. Raspberry-patched Chromium binaries, hardware video flags and automatic extension downloads are omitted; codecs and sandboxing use Alpine Chromium. Labwc sessions enable native Wayland and Wayland IME for the touch keyboard. The Chromium sandbox is not disabled.

## Update coverage and limits

APK updates retain Alpine/postmarketOS repositories. The daily GitHub build tracks explicit Raspberry source packages including browser defaults. A changed official desktop dependency/recommendation manifest stops publication for review, preventing new components from silently being missed or Pi-only packages being imported automatically.

Full printer driver collections remain excluded by user choice; the existing printer UI/basic CUPS stack is retained. Office/education suites, IDEs, Raspberry Connect, imaging/boot/GPIO tools and APT integration are intentionally absent. The Chromium binary is Alpine's, so Raspberry-specific browser patches/extensions are not implied. Hardware audio, battery, acceleration and backlight limitations remain board/kernel issues.

Native ARM headless tests cover MIME defaults, browser configuration, archive round trips and original settings dialogs, alongside existing session, touch-menu ABI and greeter tests. OpenRC setup is implemented but physical OpenRC boot is not qualified by the systemd M10 test. Physical USB media and Bluetooth peripherals need attached hardware to test.
