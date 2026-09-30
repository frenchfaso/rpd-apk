# Disposable native build candidate

Prepared workflow only. No run, browser build, production edit or publication
has been performed by this preparation task. Keep the workflow separate from
the release signing/deployment pipeline; `native-build.yml` is a reviewable
template for `.github/workflows/` on the experimental branch. Its bootstrap
push event is restricted to `codex/m10-video-build-preflight` and candidate
paths; a push always uses the units-only default. It requires the
existing candidate directory at `experiments/m10-video/chromium-candidate`.

The CI payload needs `upstream/`, `prepared/`, `patches/`, `ci/` and
`source-manifest.json`; historical reference snapshots, runner logs and the
source-audit regeneration scripts are not required by `verify-build.py` and
need not be copied to the packaging checkout. Its manifest retains their
provenance hashes, while the CI input checker verifies every actual build input.

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
A PATH wrapper enforces zero fuzz on all patch commands. Any upstream patch
that needs fuzz fails this strict preparation; it is not silently relaxed.

After preparation, the four inspected Chromium files must equal the reviewed
candidate hashes. GN must report native arm64, VA-API and V4L2 enabled. The script
discovers the two unique object targets from `ninja -t targets all`, verifies
their source input through `ninja -t query`, and compiles those generated names.
It then checks non-empty object hashes and both generated backend buildflags.
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

Remaining gates are real Alpine dependency/source preparation, generated GN
and object compilation on the runner, then optional full recipe/link/tests.
Even a passing APK build does not prove Venus NV12 export/EGL import, sandboxed
browser decoder selection or visible playback. Those remain separate M10
qualification tests; the currently exposed codecs include H264/VP8/HEVC and
exclude VP9/AV1.
