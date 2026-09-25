# Lenovo M10 Adreno 504

Experimental integration under validation; not yet published. Physical desktop
checks pass, but standard CTS found a reproducible bypass rendering error.
Do not publish yet; CTS, Piglit and trace replay qualification is incomplete.

The M10 uses its real Adreno 504 identity. Kernel support extends the existing
small-A5xx paths, supplies the SDM429 UBWC configuration, and attaches the RPM
voltage domain through the kernel power-domain API. This tablet reports factory
speed bin 10, whose Lenovo limit is 320 MHz; the integration respects that limit
(no overclock). The firmware display controller remains unchanged.

Mesa follows Alpine's complete recipe, including llvmpipe, with four patches:
Adreno 504 identification, corrected depth/stencil MSAA tile sizing, and A504-only
bypass rendering to avoid excessive geometry replay across its 136 KiB GMEM,
and generic clears on A504 to avoid fast-clear corruption in bypass. Hardware
GLES 3.1 and Chromium WebGL 1/2 have passed shader and pixel-readback tests.
This does not establish full API conformance. WebGPU adapters are unavailable;
video decoding is a separate Venus driver task.

`rpd-gpu-m10` stores its modules separately from official kernel files. A
boot-deploy hook composes GPU changes after the audio and CPU hooks, only when
the installed kernel APK, modules and official board DT match. Kernel updates
are never pinned. The existing kernel updater rebuilds this subpackage too;
unreviewed kernel changes may delay publication without blocking upstream
kernel upgrades on the tablet.

At greeter and desktop startup a bounded real rendering test selects the GPU.
If the test fails, the session uses pixman and Mesa software rendering. This
also handles a newer official Mesa release arriving before our patches.

Build checks cover real board DT composition and kernel/DT/module mismatch
fallbacks. The full Mesa APK passed 600 browser rendering frames, 6 resizes,
86 pixel comparisons with 4x MSAA, and 11 Three.js scenes on the physical GPU
desktop after resume. Chromium reported FD504 and no GPU process crashes.
These used the factory 320 MHz clock and original 500 ms hangcheck.

Reboot, login, rotation/touch/window drawing were confirmed by the user. A 20-second s2idle
cycle blanked and restored the backlight correctly; an earlier missed sleep
callback remains unexplained. Earlier headless stress also failed, so these
results apply to the physical desktop and do not establish general stability.
Official CTS/Piglit and compatible trace replay results are required before
claiming broader qualification; do not interpret Three.js passes as conformance.

Initial standard testing uses the GLES CTS revision and exact backports/patches
from Mesa 26.2.3 CI with surfaceless EGL. The information group passed 6/6 on
FD504; the first GLES2 diagnostic passed 375 cases before an image mismatch in
`dEQP-GLES2.functional.fragment_ops.random.99`. The isolated case fails in bypass
and passes in GMEM. All 100 cases in that fragment-operations group pass with
forced GMEM. These diagnostic results do not qualify the default bypass policy.
The initial depth-cache hypothesis did not fix it. A separate generic-clear
candidate passes all 100 cases while retaining bypass; full qualification of
that workaround is still pending. The running desktop still uses r1003.

Sources:
- [Alpine Mesa recipe](https://gitlab.alpinelinux.org/alpine/aports/-/tree/5be9d1d4593ed639fe9e1905cee3a791de36bff3/main/mesa)
- [Exact pmOS kernel source](https://github.com/msm89x7-mainline/linux/tree/v7.1.3-r1)
- [Posted A5xx GPMU crashdump fix](https://www.mail-archive.com/dri-devel@lists.freedesktop.org/msg637646.html)

Video audit: the inherited Venus memory reservation is disabled, so its kernel
probe stops before firmware boot. The original firmware is present and fits the
4 MiB reservation. Active clock/domain handling still needs verification. Alpine
Chromium 152 enables VA-API but leaves `use_v4l2_codec=false`; enabling Venus alone
will therefore not accelerate YouTube in that browser build. No video-decode
support is claimed by this GPU package.
