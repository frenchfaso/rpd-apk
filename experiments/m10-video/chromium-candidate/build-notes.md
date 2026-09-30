# Build resources and next checks, 2026-09-30

The retained packaging workflow/build script are from
`packaging/rpd-apk-gpu-release`, clean at commit
`51bd0df19b14472b2833cb10ab177b070c3b202d`; snapshots and source state are in
`reference/`. Its build job uses `ubuntu-24.04-arm`, a native aarch64
`alpine:edge` Docker container, a 180-minute timeout and an ephemeral build key.
The production workflow subsequently signs and deploys. The build list contains
`rpd-chromium-defaults`, not the Chromium browser source package; existing smoke
checks cover desktop/default integration, not hardware video decode. Do not
append an unqualified Chromium build to that production publication path.

The parent's [standard ARM runner preflight, run 36760452118](https://github.com/frenchfaso/rpd-apk/actions/runs/36760452118)
passed on 2026-09-30. The saved `runner-preflight-36760452118.log` records native
aarch64, four CPUs, 15 GiB RAM and 3 GiB swap. `df -hT` reports `/dev/root` as
145G total, 37G used and 108G available at startup. This measured free space is
above Chromium's pinned 100 GB free-disk planning baseline; it supersedes the
earlier capacity inference based only on advertised runner specifications.
The preflight also inventories 6.1G dotnet, 3.2G hosted tool cache and 3.5G Swift
on this disposable runner; none was removed by this task.

GitHub documents standard public ARM Linux runners as 4 CPU/16 GB RAM/14 GB SSD;
private ones are 2 CPU/8 GB RAM/14 GB SSD. The actual measured runner has more
storage than the advertised 14 GB. Chromium's Linux developer instructions
recommend more than 16 GB RAM and describe x86-64 developer checkouts, not
measured Alpine ARM package builds. Alpine uses a reduced release tarball and
already sets `symbol_level=0`, `use_thin_lto=false` and `use_mold=true`. A bounded
cold build on the free public native runner is now the first option; actual
elapsed time, peak memory and peak disk still need measurement. Concurrency
must respect the measured memory/swap budget.

Practical options that avoid a large Mac build:

| Builder | Documented resources/constraints | Assessment |
| --- | --- | --- |
| Measured free public standard ARM runner | 4 CPU, 15 GiB RAM + 3 GiB swap, 108G free at startup; existing production job timeout 180 minutes | First bounded cold-build option in a separate candidate workflow. Startup disk baseline passed; peak use and completion time remain unmeasured. |
| Larger Linux ARM runner, 4 CPU | 16 GB RAM, 150 GB SSD | Above the documented disk baseline, with limited memory headroom. |
| Larger Linux ARM runner, 8 CPU | 32 GB RAM, 300 GB SSD | Capacity fallback only if the free run proves insufficient; USD 0.014/min, up to USD 5.04 for a 360-minute execution, excluding other billed storage/services. Runtime is unmeasured. |
| Dedicated remote/self-hosted Linux aarch64 builder | Provision sufficient free disk/RAM explicitly; persistent build storage is possible | Works with a native Alpine container without retaining a Chromium tree on the Mac. No available machine or provider was selected. |

GitHub larger runners require an organization/enterprise on Team or Enterprise
Cloud, are paid even for public repositories, and do not consume included
minutes. Eligibility for this account has not been checked. All hosted jobs have
a six-hour execution limit; a self-hosted job has a five-day platform limit,
subject to its configured workflow timeout. Larger runner labels are configured
by their owner, so there is no assumed ready-to-use eight-core label here.

Repeat architecture/free-disk/memory preflight on the actual build job before
large downloads; verify Alpine toolchain availability and set a bounded runtime.
Retain the release tarball/checksums and exact auxiliary port files from the
pinned Alpine recipe. First complete `abuild` preparation and inspect generated
GN args/buildflags for aarch64 V4L2 plus VA-API. Compile the two changed `.cc`
units first; derive their exact object target names from Ninja's generated
target list rather than guessing paths. Then complete the normal recipe
build/check/package sequence with an ephemeral signing key. Record elapsed
time and peak storage/memory. Upload review artifacts only; production signing,
publication and desktop default changes are separate steps after qualification.

The isolated `ci/` draft was independently checked against official
[abuild source revision 03444ca1](https://github.com/alpinelinux/abuild/blob/03444ca1b6fa10d1717d024a6e94ee27e3ed50f2/abuild.in).
`deps` installs calculated build/runtime dependencies; the dispatcher accepts
the defined `verify` function as well as documented stages. Pinned Chromium
`prepare()` includes GN generation. Normal `abuild -r` performs a `clean`
before unpack/prepare/build/check/package, so the optional full gate discards
and rebuilds the initially compiled objects. On aarch64 the pinned recipe
retains its normal checks. The pinned Alpine recipe provides `ninja` through
[Samurai 1.3](https://github.com/alpinelinux/aports/blob/a44854115ef1a1cda0c41b3e6f0974f51755d736/main/samurai/APKBUILD);
its [official tool implementation](https://github.com/michaelforney/samurai/blob/1.3/tool.c)
supports `-t targets all` and `-t query` in the formats used by the CI selector.
The twelve offline CI fixtures passed independently; generated GN/Ninja graph
discovery and compilation remain runner gates. Retained source snapshots and
hashes are in `reference/` and the manifest.

After a successful build, native M10 browser qualification must verify normal
sandbox operation, codec selection, NV12 export/import and visible rendering,
then EOS, seek, repeated sessions and suspend/resume. The stateful decoder
requests sixteen 2 MiB H264 OUTPUT buffers for up to 1080p (32 MiB before
CAPTURE buffers and other browser memory), so native buffer/resource behavior
also needs observation. Browser success cannot be inferred from FFmpeg CRCs or
a runner's compile result.

Primary references checked on 2026-09-30:

- [Pinned Chromium build requirements](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/docs/linux/build_instructions.md)
- [Standard runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [Larger runner specifications](https://docs.github.com/en/actions/reference/runners/larger-runners)
- [Runner prices and eligibility](https://docs.github.com/en/billing/reference/actions-runner-pricing)
- [Actions execution limits](https://docs.github.com/en/actions/reference/limits)
- [Pinned stateful decoder buffers](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/gpu/v4l2/v4l2_stateful_video_decoder.cc)
