# Repository and build reference

## Local build

Run `scripts/build.sh` as root in a disposable **aarch64 Alpine edge** container. It creates an unprivileged builder and a throwaway build key, compiles individual APKs with abuild, then installs the complete M10 profile into a clean root for dependency/file checks. Output: `out/`.

`upstream.lock.json` pins published tarballs and hashes. The release tracker runs with Python 3, GnuPG and dpkg (for Debian version ordering), as provided by the Ubuntu prepare job. `scripts/generate.py` regenerates upstream APKBUILDs; local changes are ordinary patches under each port. Source archives and license notices must be retained with distributed binaries.

Session configuration is in `/etc/xdg/rpd/`. `rpd-session` initialises standard per-user `~/.config/labwc` files once, so native preference tools edit the compositor configuration actually in use. Those files are never overwritten on upgrade; new system defaults remain in `/etc/xdg/rpd/labwc`. Panel customizations use `~/.config/wf-panel-pi/`. APK preserves modified `/etc` files with standard `.apk-new` handling.

## Updates and publication

GitHub Actions checks the signed official Trixie source index daily, selects our explicit component allowlist, validates tarball hashes and rebuilds native ARM64 APKs against Alpine edge. The build job uses a disposable signing key and runs clean-root installation and headless graphical tests. A separate job replaces the test signatures using the dedicated `APK_SIGNING_KEY` Actions secret, checks the production signatures and installation, and publishes with GitHub Pages. The production key is never exposed to upstream build scripts or included in public artifacts. The Mac is not required.

Every run allocates increasing package revisions in Git before building, so `apk upgrade` can install ABI rebuilds. Failed builds leave a skipped revision but do not deploy. Scheduled runs can be delayed or disabled by GitHub's inactivity policy; the Actions page shows their status. The workflow can also be started manually.

This follows *published source packages*, not development commits. Unknown layouts, unsupported version formats, archive changes without version bumps, patch failures and failed tests stop publication. Changes to the official desktop dependency/recommendation set stop publication until `upstream-desktop-components.json` is reviewed; they do not automatically enter the hardware-independent allowlist. A maintainer must adapt incompatible upstream changes. Headless tests do not qualify physical touch/GPU/display behavior.

Public key: `keys/rpd-apk.rsa.pub`. The private counterpart is held as an encrypted GitHub Actions secret, with a local backup outside Git. Repository write access and workflow changes must therefore be trusted. Actions are pinned to commit IDs. Local builds use a throwaway key by default.

Client updates use `apk update && apk upgrade`. No unattended root upgrades or reboots are enabled on the tablet. Alpine and postmarketOS packages keep their original repositories.

