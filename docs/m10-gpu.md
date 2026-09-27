# Lenovo M10 Adreno 504

Experimental integration under qualification; not yet published. The draft
checkpoint now uses Mesa 26.2.3-r1010 and the matching kernel-module bundle r55.
Installed M10 packages remain on the earlier release during isolated tests.

The `shared-max` hardware fault is fixed in a production-form candidate by
bounding A504 barrier register residency. All 195 dEQP compute cases pass;
Khronos compute completes 37 Pass / 2 Skip. The full 4,101-case Khronos GLES3.1
list completes 2,588 Pass / 1,505 Skip / 8 Fail, without GPU errors. Its eight
failing names occur in the pinned A530 failure list; no shared cause is claimed.

Piglit quick_shader completed 18,018 cases with 5,880 Pass / 12,127 Skip /
7 Fail / 2 Crash / 2 Warn. Both crashes are IR3 compiler worker stack exhaustion
on musl, independently reproduced on r1008 and r1009 packages. Chimera's pinned
thread-stack patch makes both unchanged UBO tests pass in 37--41 seconds,
without GPU errors. The combined candidate is undergoing the full profile
again, using the upstream A530 180-second timeout. Public traces, exact final
APK checks and device lifecycle checks still gate publication.

The driver uses the real Adreno 504 identity, SDM429 UBWC configuration and
kernel power-domain APIs. This tablet's factory speed bin 10 selects 320 MHz.
The integration keeps that limit, automatic runtime power management and the
original 500 ms hangcheck. The firmware display controller remains unchanged.

Mesa retains Alpine's complete driver recipe, including software fallback.
A504 corrections cover identification, depth/stencil MSAA layout, bypass
rendering, clears, transform feedback, compute submission boundaries and cached
blit coordinates. The IR3 barrier/register-allocation backports fix shared-memory
compute compilation. See the Mesa port README for the exact patch series.

Kernel changes cover retained-state reset, recovery ordering and reference
ownership, CX dependency lifetime and shadow mapping teardown. A504's bounded
progress callback samples the reserved SP0 fragment-discard counter through
RBBM. This lets long legitimate draws complete while retaining the common
three-retry recovery bound. The watchdog does not read the SP selector register:
that diagnostic version restarted the M10 in the recovery probe.

The RBBM-only trial passes deliberate-hang recovery, subsequent rendering and
the maximum-framebuffer case at normal policy. That framebuffer case also
passes with the actual Mesa APK libraries in an isolated prefix. Full packaged GLES 3.1 passes with17,403 Pass /20,399 Skip. Remaining
regression and device lifecycle checks are still pending; these gates do not
establish production readiness or Khronos conformance.

Earlier unchanged dEQP selections produced the totals below. GLES2 used the
register-series candidate, as did a later complete GLES3 run; GLES3.1 has
actual r1008 package coverage. EGL now also has a separate clean full run
on the exact r55/r1008 packages. Full packaged GLES3 also completed all
44,768 cases with identical outcomes to the register-series reference,
without crashes, timeouts or GPU errors:

| Suite | Pass | Skip | Fail | Warn |
| --- | ---: | ---: | ---: | ---: |
| GLES2 | 17,041 | 116 | 5 | 3 |
| GLES3 | 44,556 | 194 | 8 | 10 |
| GLES3.1 | 17,403 | 20,399 | 0 | 0 |
| EGL | 2,637 | 1,152 | 0 | 0 |

No imported A530 failure baseline was used. The GLES2/3 failure names also occur
in Mesa's pinned A530 failure list; this does not prove an A504 hardware limit.
EGL's eight GPU faults overlapped robustness tests and did not restart that run.
The earlier selector-read kernel still failed the separate recovery probe,
which is why passing suite totals alone did not permit a release. Piglit,
public trace replay and final package/lifecycle qualification remain required.

The first full EGL run on the exact r55/r1008 package payloads recorded
2,635 Pass, 1,152 Skip, 1 Flake and 1 Timeout during concurrent interactive
Chromium use. Both anomalous cases passed individually afterward. A separate
full idle repeat completed all 3,789 cases: 2,637 Pass / 1,152 Skip, without
failures, flakes, timeouts or hangs. Its eight GPU faults overlap robustness
cases; buffered timing establishes correlation, not exact attribution.
The original anomalous result is retained.

labwc r154 defers renderer recreation until Wayland finishes emitting its
lost signal. This avoids destroying the signal owner while temporary dispatcher
listeners are attached. Upstream unit tests and the existing touch test pass.
A private real-hardware trial survived the reset notification with the same
greeter process and no assertion; subsequent packaged EGL rendering passed.
The current combined compositor/Mesa trial remains temporary.

`rpd-gpu-m10` keeps modules separate from official kernel files. Its boot-deploy
hook composes GPU changes after audio/CPU changes only when the kernel APK,
module ABI and official board DT match. Kernel upgrades remain unrestricted.
The existing updater rebuilds the optional modules; incompatible upstream
changes can delay these modules without blocking official kernel upgrades.
At greeter/session startup, a bounded rendering check selects acceleration or
falls back to pixman/software rendering.

Earlier physical-desktop checks demonstrated GLES 3.1 and Chromium WebGL 1/2,
including rotation, touch and resume. They are historical integration evidence,
not substitutes for the standard Mesa procedures above. ES 3.2 parity is a
later checkpoint. No WebGPU support is claimed.

Hardware video decoding is a separate Venus task. Its inherited memory
reservation is disabled; firmware is available, but clock/domain and decode
validation remain. The inspected Alpine Chromium 152 build enables VA-API and
disables `use_v4l2_codec`; enabling Venus alone does not enable decoding through
that browser backend. No hardware video support is included in this checkpoint.

Sources:

- [Alpine Mesa recipe](https://gitlab.alpinelinux.org/alpine/aports/-/tree/5be9d1d4593ed639fe9e1905cee3a791de36bff3/main/mesa)
- [Exact pmOS kernel source](https://github.com/msm89x7-mainline/linux/tree/v7.1.3-r1)
- [Posted A5xx GPMU crashdump fix](https://www.mail-archive.com/dri-devel@lists.freedesktop.org/msg637646.html)
