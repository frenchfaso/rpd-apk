# Mesa for Adreno 504

The r1010 checkpoint adds an A504 barrier-residency bound and an existing musl
thread-stack portability fix. Its signed APK libraries complete all 195 dEQP
compute cases and the 4,101-case Khronos GLES3.1 list without crashes, timeouts
or GPU errors. The eight retained Khronos functional failures are documented
below. Full quick_shader completes with the same retained functional failures
and no crashes/timeouts or GPU errors. Public replay is repeatable, with two
documented one-level image differences against A530. Physical desktop, suspend/resume and permanent boot checks pass on the M10.
These tests do not establish Khronos conformance.

Based on Alpine aports main/mesa at `5be9d1d4593ed639fe9e1905cee3a791de36bff3`.
The upstream build options and subpackages are preserved, including llvmpipe.
The package is aarch64-only with a revision offset of 1000.

## Driver changes

- Recognize Adreno 504 in the small-A5xx family.
- Fix depth/stencil MSAA accounting on the 136 KiB GPU.
- Prefer system-memory rendering and generic clears on A504.
- Tile depth/stencil resources while keeping color resources linear.
- Reserve complete fragment input slots when the vertex shader captures
  transform feedback.
- Give each A504 compute dispatch its own Gallium batch and DRM submission,
  without forcing completion waits or changing other GPUs' batching.
- Cache the A504 fragment-coordinate shader used for in-bounds RGBA8/BGRA8
  NEAREST blits.
- Backport the upstream IR3 register-budget series from
  [Mesa MR 43896](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/43896).
  Seven patches retain their upstream commit IDs and attribution. The eighth
  commit, `1cca5f65775b2ac55e55e42e094a17abb85dfe58`, is already in the base.
  Upstream CI expectation changes are deliberately omitted. The series bounds
  split register banks and the simultaneous waves of barrier workgroups.

- Bound A504 simultaneous barrier residency more conservatively, retaining
  API limits and normal register allocation for other shader stages.

The updater preserves these patches when following Alpine releases and fails
if the upstream recipe structure changes. Patches already absorbed by a future
Mesa release need review; they must not be silently reversed or dropped.

## Qualification status

`26.2.3-r1010` is the current draft. The following broad results refer to r1008. Its complete patch stack applies to the pinned archive
with zero fuzz. Of 26 source files compared with the private candidate, 24
match exactly and two differ only by existing explanatory comments.

The private register-series candidate passes all 136 official GLES 3.1 shared
variable cases. The earlier maximum-framebuffer watchdog case subsequently
passes with the bounded kernel progress callback; the full packaged GLES 3.1
run completed 17,403 Pass / 20,399 Skip, with no failures or GPU errors.
Private register-series GLES 2 regression completed 17,041 Pass, 116 Skip,
5 Fail and 3 Warn, matching the preceding candidate. Full register-series
GLES3 also completed 44,556 Pass / 194 Skip / 8 Fail / 10 Warn on the earlier
9FEE kernel; exact r55/r1008 package qualification remains separately tracked.

All 21 r1008 APKs were built and signature-checked. Their libraries run in a
private prefix; global packages remain unchanged. The first packaged full EGL
run covered all 3,789 cases with 2,635 Pass, 1,152 Skip, 1 Flake and 1 Timeout
while the user also used Chromium. Both anomalous cases passed an isolated
repeat, but this does not turn the original result into a clean full pass.
A separate full idle repeat completed all 3,789 cases: 2,637 Pass / 1,152
Skip, no other outcomes or hangs. Eight GPU faults overlap robustness cases;
this is timing correlation, not exact attribution. Full packaged GLES3 also
completed 44,556 Pass / 194 Skip / 8 Fail / 10 Warn, with every outcome
identical to the prior register-series run and no crashes, timeouts or GPU
errors. No publication or certification claim.

The production-form r1009 candidate additionally completes the full 4,101-case
Khronos GLES3.1 list: 2,588 Pass / 1,505 Skip / 8 Fail, with an empty monitored
kernel log and no crashes/timeouts. All eight failing names also occur in the
pinned A530 failure list; that comparison does not prove a common cause or
convert failures into passes. The combined r1010 candidate also completes
Piglit quick_shader with
5,882 Pass / 12,127 Skip / 7 Fail / 2 Warn and no crash, timeout or GPU error.
The signed r1010 APK libraries reproduce all 4,101 Khronos outcomes exactly
and pass both UBO stack regressions. The actual r56 kernel-module APK repeats
all Khronos outcomes without GPU errors. The final desktop lifecycle checks
pass; see `docs/m10-gpu.md` for scope and retained failures.

The qualification includes the CTS selections above, full quick_shader,
public replay and packaged desktop/runtime-PM lifecycle checks. Known clipping
and other rendering failures remain failures; no A530 expected-failure
baseline is imported. No Khronos certification is claimed.

Official kernel upgrades remain independent, and software rendering remains
available. This checkpoint does not enable Vulkan or video decoding on A504.

The r1010 checkpoint additionally carries Chimera's unchanged `musl-stacksize.patch`
from cports commit `73188229fd4f9666a9cec99036fd152e179b8c46`:
<https://github.com/chimera-linux/cports/blob/73188229fd4f9666a9cec99036fd152e179b8c46/main/mesa/patches/musl-stacksize.patch>.
This provides 8 MiB stacks to Mesa C11 workers on non-glibc systems. Two
unchanged Piglit UBO cases exhaust musl's default stack in IR3 copy propagation
(2,066 recursive frames confirmed in the guard page), independently of the
A504 barrier fix. This is a userspace portability fix, not a GPU workaround.
The qualified checkpoint retains the known functional failures documented above.
