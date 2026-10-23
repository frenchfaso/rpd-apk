# Temporary polkit security backport

Based on postmarketOS `extra-repos/systemd/polkit`, upstream 127, retaining its logind build, PAM policy, package split, users and ABI. The unchanged source archive and PAM hashes match the official recipe. The original recipe is retained in `upstream-APKBUILD.reference`.

Apply the complete upstream cookie-reader sequence:

- `7e122c8a5120c2aae2d9d44a26796dc18f5b677c`: bound stdin input (CVE-2026-4897).
- `39601309eb3e5e88a1c1fbda9a272ba8691f1bf3`: reject long input immediately rather than draining an indefinitely open stream.
- `eea172967848bb4c5a407329f40c0e45de0d187e`: reject initial NUL before length subtraction (CVE-2026-85498, a regression in the initial fix).

The installed M10 helper matches the authenticated pmOS binary with the original unbounded getline path. The second CVE is prevented by this candidate, rather than attributed to that unpatched installed binary.

`check()` compiles the actual patched cookie function as an ordinary process linked with GLib. It tests length boundaries, EOF/newline/NUL handling, a writer that keeps stdin open and legacy argv compatibility; it never executes the setuid helper. Full upstream system-bus integration tests are not run by this recipe and must remain part of separate package/device qualification. `verify-cookie.py --sanitize <source>` adds address/undefined-behavior checks where supported.

This is a candidate, not yet a published or hardware-qualified replacement. Its revision 100 distinguishes the overlay from pmOS revision 2; a newer upstream version can supersede it normally. Same-version pmOS revisions need review before removing the overlay. No updater or version pin is installed on the tablet.
