# Disposable native build candidate

The workflow is isolated from the release signing/deployment pipeline.
`native-build.yml` is a reviewable
template for `.github/workflows/` on the experimental branch. Its bootstrap
push event is restricted to `codex/m10-video-build-preflight` and candidate
paths; a push always uses the units-only default. It requires the
existing candidate directory at `experiments/m10-video/chromium-candidate`.

The CI payload needs `upstream/`, `prepared/`, `patches/`, `ci/` and
`source-manifest.json`; historical reference snapshots, runner logs and the
source-audit regeneration scripts are not required by `verify-build.py` and
need not be copied to the packaging checkout. Its manifest retains their
provenance hashes, while the CI input checker verifies every actual build input.

The first units-only push, commit `8bf04c9`, reached normal Alpine dependencies
and fetch but failed before unpack/GN/C++ compilation in
[run 36763888403](https://github.com/frenchfaso/rpd-apk/actions/runs/36763888403).
The patch checksum had been prepended while its source was appended. Abuild's
`default_fetch` consumes checksums positionally; the `.879e9d75` rename suffix
proved it had compared the Chromium archive against the broker patch checksum.
The candidate now appends both entries, preserving every original source and
checksum. Before downloads, the CI checker verifies all positional pairs and
the unchanged original entries. Offline fixtures exercise the unchanged primary
abuild `default_fetch` function with local files: correct order passes, reversed
entries and corrupted bytes fail. No source checksum was refreshed or bypassed.

The corrected [run 36765877955](https://github.com/frenchfaso/rpd-apk/actions/runs/36765877955)
verified every source checksum and unpacked normally, then our global zero-fuzz
wrapper rejected 11 unchanged Alpine patches during `default_prepare`.
The wrapper now requires zero fuzz for the two named candidate patches and
passes official Alpine/copium patches directly to the normal patch tool with
their recipe arguments. Their normal context policy and visible fuzz/offset
diagnostics are retained. Real-patch fixtures prove that a context-mismatched
official fixture follows the standard policy while the same candidate fixture
fails, even if a caller supplies `--fuzz=2`. The actual native preparation and
compiler results remain required; no failed patch is skipped.

[Run 36767421564](https://github.com/frenchfaso/rpd-apk/actions/runs/36767421564)
completed normal preparation, generated 31,613 GN targets, and matched all four
reviewed source hashes. It then failed the original `target_cpu` guard, which
required an explicit argument and did not retain the declared value. The
[pinned BUILDCONFIG](https://github.com/chromium/chromium/blob/d04cdb24d67b081f6cf80200ffc5233f44b61109/build/config/BUILDCONFIG.gn#L49)
resolves empty CPU/OS arguments to the native host for Linux. The checker now
retains every raw GN argument plus runtime/BUILDCONFIG/tool-version evidence
before validation. The actual small BUILDCONFIG and progressively saved raw
argument report are uploaded even if a GN query or argument check fails.
It accepts native defaults only on Linux/aarch64 with that
exact pinned BUILDCONFIG hash; explicit CPU/OS must be arm64/Linux. Independently,
both completed objects must be little-endian ELF64 with AARCH64 machine type.
These changes preserve normal recipe defaults and require actual compiler proof.

[Run 36769567466](https://github.com/frenchfaso/rpd-apk/actions/runs/36769567466)
passed those checks with declared CPU/OS both empty, effective native arm64,
both backends enabled, and two unique generated object targets. Ninja ran
1,557 of 4,516 dependency actions before its Rust allocator dependency rejected
`-Z` options. The direct Ninja shell had not inherited the recipe's global
`export RUSTC_BOOTSTRAP=1` from the earlier abuild subprocess. The wrapper now
mirrors that exact export and `build()`'s open-file limit 4096, recording their
effective values and actual Rust version. It preserves every compiler option.
Input guards require the original global export and build-limit contract;
real child-process fixtures fail if either wrapper setting is omitted.

The remaining `_configure()` exports (C/CPP/CXX flags and AR/CC/CXX/NM, plus
incoming LDFLAGS) are read by
[unbundle GN](https://github.com/chromium/chromium/blob/d04cdb24d67b081f6cf80200ffc5233f44b61109/build/toolchain/linux/unbundle/BUILD.gn#L8)
at generation and embedded literally in
[tool commands](https://github.com/chromium/chromium/blob/d04cdb24d67b081f6cf80200ffc5233f44b61109/build/toolchain/gcc_toolchain.gni#L357).
The checker retains each actual generated C++ command, including those flags,
and the wrapper retains the two small actual toolchain source files/hashes.
`VPYTHON_BYPASS` and the depot-tools PATH extension belong to `check()`; normal
full abuild retains that phase. The units-only gate executes neither checks nor
final browser links and does not claim their qualification.

[Run 36772429374](https://github.com/frenchfaso/rpd-apk/actions/runs/36772429374)
verified the unchanged Chromium archive and fonts, then stopped before unpack
because Codeberg returned HTTP503 for the official copium archive. Standard
`abuild fetch` now retries only that exact transient HTTP503, at most three
attempts with five-second delays, reusing successful downloads in the same run.
Every attempt's raw log/status is retained. Hash failures, HTTP404 and all
other errors fail immediately; no checksum or URL changes. Normal
`abuild verify unpack prepare` follows only after fetch succeeds.

The manual default builds only the two changed C++ objects. The optional
`full_recipe` dispatch input continues to normal `abuild -r` only after those
objects and generated backend flags pass. It uses the recipe's normal
build/check/package functions and an ephemeral key; it adds no check or
checksum bypass. Test-signed APKs are review artifacts, not a published package.
Normal `abuild -r` cleans the source directory and repeats unpack/preparation;
the two proof objects are rebuilt. Its source downloads remain cached only
within this disposable attempt.

Before large downloads, both host and container require native aarch64, at
least four CPUs, 100 GiB free, 14 GiB effective RAM and 17 GiB RAM plus swap.
`JOBS` accepts 1 through 4 and the Ninja wrapper bounds the recipe's calls.
The job records its Alpine image digest, edge repository/package versions,
aports archive hash, resource samples and GNU time maximum process RSS. Edge
dependencies remain moving inputs; this is validation of the pinned recipe
against the runner's recorded toolchain, not a reproducible dependency snapshot.

Inside the disposable container it downloads the exact aports commit archive,
extracts only `community/chromium`, verifies the original APKBUILD SHA-256,
applies the recipe candidate with zero fuzz and no offsets, and checks retained
candidate hashes. Standard `abuild deps` and `fetch verify unpack prepare` then
install dependencies and verify every recipe source checksum. The pinned
`prepare()` already includes copium, normal Alpine preparation and GN generation.
A PATH wrapper enforces zero fuzz on our recipe and broker candidate patches.
Unchanged official patches use their normal Alpine/copium policy; all failure
statuses remain fatal and their application diagnostics remain in the logs.

After preparation, the four inspected Chromium files must equal the reviewed
candidate hashes. GN must report native arm64, VA-API and V4L2 enabled. The script
discovers the two unique object targets from `ninja -t targets all`, verifies
their source input through `ninja -t query`, and compiles those generated names.
It then checks non-empty AARCH64 object hashes and both generated backend buildflags.
No object path is assumed before GN runs. Chromium never executes during this
workflow; its normal sandbox and the candidate's narrow decoder permissions
remain intact.

The container attempt is bounded at 300 minutes within a 330-minute job, leaving
time for cleanup and artifact upload. Failure and timeout logs are uploaded with
`always()`. Only review logs, hashes, patches and optional completed APKs/public
test key are uploaded; source trees, tarballs and the private key remain on the
disposable runner. No production signing secret is requested.

Local checks, without downloads or compilation:

```sh
python3 experiments/m10-video/chromium-candidate/ci/test-verify-build.py
sh -n experiments/m10-video/chromium-candidate/ci/build-in-container.sh
```

The next runner must repeat normal preparation, qualify declared/effective GN
arguments, and compile both objects. Full recipe/link/tests remain a later gate.
Even a passing APK build does not prove Venus NV12 export/EGL import, sandboxed
browser decoder selection or visible playback. Those remain separate M10
qualification tests; the currently exposed codecs include H264/VP8/HEVC and
exclude VP9/AV1.
