# Raspberry Pi Desktop for Lenovo M10

The **Raspberry Pi OS ARM Trixie** desktop on postmarketOS/Alpine, with its menu,
theme, LightDM login, Chromium, VLC and essential utilities. Includes M10 support
for touch, rotation, the on-screen keyboard, Bluetooth, USB OTG, internal speakers, brightness and battery.
This ports the desktop; the underlying OS remains postmarketOS, managed through APK.

## Install

Requires a **Lenovo Tab M10 TB-X505L** already running **postmarketOS edge aarch64
with systemd**, working Wi-Fi and an existing user with `sudo` access.
Use an installation without the console/Buffyboard profile: LightDM becomes the main login.
These commands do not install postmarketOS or unlock the tablet.

```sh
# Add the repository and signing key, then refresh the APK index.
wget https://raw.githubusercontent.com/frenchfaso/rpd-apk/main/scripts/install-repository.sh
sudo sh install-repository.sh

# Install the desktop and configure host services.
sudo apk add rpd-desktop-m10
sudo rpd-configure-host YOUR_USERNAME
sudo reboot
```

Replace `YOUR_USERNAME` with your existing username. Sign in at the graphical login after rebooting.

## Update

```sh
sudo apk update && sudo apk upgrade
```

GitHub Actions tracks official Raspberry component releases and publishes signed
APKs after building and testing. Incompatible upstream changes may require manual
maintenance. Raspberry board-specific packages are excluded.
Official kernel updates are never blocked: M10 modules require a matching build
and may remain temporarily unavailable after a kernel upgrade.

The metapackage restores the desktop and integrations, not personal files, Wi-Fi
credentials or battery calibration history. Battery charge and runtime are estimates.

Details: [desktop](docs/DESKTOP.md), [battery](docs/BATTERY-TELEMETRY.md),
[audio](docs/M10-AUDIO.md), [USB OTG](docs/M10-USB-OTG.md), [optional LVM storage](docs/LVM-M10.md),
[building and publishing](docs/REPOSITORY.md).
