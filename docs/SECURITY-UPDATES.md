# Security updates

The M10 kernel is a board-specific postmarketOS kernel. Its current Linux 7.1
series is EOL. The temporary `7.1.3-r100` package backports eight reviewed fixes;
it does **not** provide the coverage of a maintained kernel series. Moving the
board support to a maintained kernel remains separate work.

The exact fixes, original commits, patch hashes and conditional applicability are
recorded in [security-fixes.json](../ports/linux-postmarketos-qcom-msm89x7/security-fixes.json).
Both the complete kernel and matching M10 modules consume the same patches and
verified configuration. Stock GPU-module fallback also retains the two MSM fixes.

The updater tracks the signed official base separately from our higher package
revision. It retains the reviewed fixes while that base is unchanged. A newer
official base is reported for review; unexpected same-version changes or failed
authentication stop the check. It never silently removes security patches or
automatically ports board support to another kernel series.

There is no exact kernel dependency or intentional kernel hold. A higher official
kernel version, such as `7.1.4-r0`, can upgrade normally; optional M10 extensions
skip loading until a matching rebuild is available. However, APK considers
`7.1.3-r100` newer than `7.1.3-r2`. A same-version official revision therefore needs
a reviewed newer overlay or an explicit authenticated handover. A failed module
check is fallback protection, not proof that an untested kernel will boot.
Reboot after installing a kernel update before manually restarting hardware
services: the running kernel is still the previous build until that reboot,
even when both packages share the same kernel release string.

GNOME Web uses the updated WebKitGTK 6.0 package. The browser sandbox remains
enabled. Polkit includes the bounded-input fix and both follow-up corrections.
Squeekboard updates memmap2 to 0.9.11 and backports the GLib iterator correction;
its locked, offline Rust dependency graph is checked during compilation. A scanner
may still identify GLib 0.18.5 by version, so the backported fix is documented in
the package sources rather than presented as a new upstream GLib release.

On 23 October 2026 the optional Alpine Chromium provider was still below the
Chrome 156.0.8078.47 fix for [CVE-2026-113303](https://chromereleases.googleblog.com/2026/10/stable-channel-update-for-desktop_02018666648.html).
It is not included in this browser profile. Check for a corrected provider before
installing it separately; browser configuration files are not a Chromium engine.

Build jobs use temporary signing keys. A separate job signs the tested repository
with the existing production key; users keep the same repository trust anchor.
Source archives, package provenance and validation reports accompany publication.
Device qualification remains necessary for kernel changes and major WebKit
graphics changes. Do not infer real GPU, decoder or suspend support from a
successful compiler or headless test alone.
