# Native GTK4 WebKit security candidate

This is an ARM64 musl build of WebKitGTK 2.54.2 for the existing GNOME Web
browser. It retains the `libwebkitgtk-6.0.so.4` and
`libjavascriptcoregtk-6.0.so.1` ABI. It does not replace Mesa, the kernel,
GStreamer plugins or the browser with a different distribution's binaries.

The recipe follows Alpine's GTK4 package and the reviewed 2.54.1 GTK3 upgrade
in [aports !109558](https://gitlab.alpinelinux.org/alpine/aports/-/merge_requests/109558).
`upstream.json` records the exact source and recipe revisions. The only upstream
patches retained for ARM64 are Alpine's unchanged C-loop and X11 include fixes.
The source archive uses normal abuild SHA512 verification; its SHA256 was also
checked against the upstream HTTPS release sums. No independent GPG verification
of the source archive is claimed.

Sandboxing, JIT, WebAssembly, WebGL/OpenGL, Wayland, GStreamer/GL and Media Source
remain enabled. Vulkan stays disabled because this device's graphics stack does
not provide it. The existing Alpine clang/lld, reduced debug symbols and fortify
workaround remain unchanged. Compilation and linking each use a single heavy-job
slot, following Alpine's native ARM64 build approach.

The separate `webkit-candidate.yml` workflow produces signed test APKs, exact
sources, public key and build receipts. It has no production signing key or
publication step. The private test key stays in the disposable container.
The initial job allows 330 minutes. Alpine's related 2.54.1 native ARM64 job took
about 108 minutes on different hardware; this is not an estimate for GitHub's
runner. The workflow records actual CPU, RAM/cgroup limits, disk and image digest;
peak RAM and scratch-space requirements still need measurement.

Checks reject disabled required features and verify that the built and installed
WebKit/JSC libraries export version 2.54.2. Installing stock Epiphany in the
container also checks package dependency resolution. The release tarball omits
the upstream GTK test runner. These checks do not qualify browser-process sandbox
runtime, rendering, FD504 acceleration, Venus playback or suspend/resume; those
must pass on the M10 before production integration. No sandbox bypass is used.
