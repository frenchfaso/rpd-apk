# Lenovo M10 Adreno 504

Integration is under validation; these changes have not been published yet.

The M10 uses its real Adreno 504 identity. Kernel support extends the existing
small-A5xx paths, supplies the SDM429 UBWC configuration, and attaches the RPM
voltage domain through the kernel power-domain API. GPU clocks are initially
limited to 320 MHz. The firmware display controller remains unchanged.

Mesa follows Alpine's complete recipe, including llvmpipe, with two patches:
Adreno 504 identification and corrected depth/stencil MSAA tile sizing. Hardware
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
fallbacks. Hardware checks must additionally cover reboot, Chromium, rotation,
brightness, audio, and suspend/resume before a release is considered validated.

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
