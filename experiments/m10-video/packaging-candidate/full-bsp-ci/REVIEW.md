# Experimental full M10 BSP build — review before dispatch

Status: **local candidate only; no push, dispatch, build, publication or device change**.
The Chromium full-build workflow is independent and untouched.

## Exact scope

Use the retained final `apk-qualification/input/` fixture, 108 files / 598,799
bytes. The candidate hard-pins `input-manifest.json` SHA256
`bf24ace60055c30926bc5bc32447dd8572ed298a4a14323f34fbb352c9c1514f`.
No fixture or existing VIDEO-ONLY proof is changed. Source code and checksums
remain exactly those reviewed for the optional decoder.
Six existing local `__pycache__/*.pyc` files are unmanifested generated caches;
the input audit reports them explicitly and stages only the 108 pinned files.
Any other extra, missing, symlinked or changed input fails. No generated caches
are executed or copied into the builder.

Normal `abuild -r` first builds `rpd-cpu-topology-m10`, then full
`rpd-backlight-m10`. The combined recipe builds fresh genuine vmlinux/exports,
GPU, backlight, OTG, battery, charger and audio modules, GPU userspace probe, current
base/audio DTs and all ten private decoder modules. No desktop or Mesa source
build is included. SDK packages use standard authenticated Alpine repositories;
`abuild deps` records the genuine installed SDK before the unchanged full run.

The builder has one disposable key. Only its public key is retained. No
production secret, production key, APK Pages publication, main merge or device
installation occurs. `abuild -r` retains its normal build/check/package flow and
dependency cleanup; its documented CLEANUP setting retains srcdir only until
the separate real-artifact audit. The disposable container is then removed.
Reference: [official abuild configuration](https://github.com/alpinelinux/abuild/blob/3.18.0_rc5/abuild.conf.in).

## Resources and lifecycle

- The first push of this workflow on `codex/m10-video-full-bsp` starts the
  bounded trial and registers the new workflow. The push trigger matches only
  that branch and this workflow file; subsequent source-only corrections need
  manual dispatch. GitHub requires an initial registered run for dispatching a
  branch-only workflow; this avoids changing the default branch. See the
  [official dispatch rules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).
  Manual dispatch is restricted to `codex/` branches, native public
  `ubuntu-24.04-arm`. Local Mac/Podman execution fails before Docker operations.
- Immutable Alpine image
  `alpine@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000`,
  already recorded by the successful Chromium ARM units build. Record actual
  image, repositories, tool/program and authenticated package versions.
- Require at least four host CPUs, 8 GiB effective RAM and 20 GiB free disk;
  container limit is two CPUs, 12 GiB RAM and 14 GiB RAM plus swap. The recipe and
  environment use two compile jobs. No kernel/source build happens on the Mac.
- Container deadline is 180 minutes; step/job bounds are 190/210 minutes, allowing
  failure evidence and cleanup. Full BSP peak size/time remain unmeasured.
- Sample host free disk/memory, Docker memory/CPU/block I/O and writable layer
  size every 15 seconds. Stop only this container below 8 GiB free or above
  12 GiB writable-layer bytes; monitor failure also fails the trial. These sampled
  limits bound a trial, not an atomic filesystem quota.
- Read-only mounts expose only candidate scripts, source fixture and manifest.
  Owned `/build`, `/home/builder`, package DB, sources, SDK changes and private key
  live inside the disposable container. Only the runner's unique review directory
  is mounted writable. It contains small reports/logs, public keys and APKs.
- `always()` cleanup and artifact upload retain failures too. An abruptly killed
  hosted runner can prevent upload; no claim of guaranteed recovery in that case.
- The runner joins the container log stream and records its exit status before
  accepting success. A failed logger fails the trial; error cleanup still stops
  the owned container and collects the available evidence.

## Output gates

`verify.py` checks real output data, without executing a module or GPU probe:

1. Exactly eight expected APK identities; actual `apk verify` using only the
   disposable public key; actual SHA256/size, dependency links and unmodified
   maintainer scripts.
2. Optional `supported:true`, decoder-only inventory of exactly ten AArch64
   ELF64 ET_REL modules, each byte hash/vermagic/depends/SRC matching `kernel.json`.
   Core/decoder SRC and qualified C hashes remain those of the native-tested
   source. No encoder or standard installed media-module replacement.
3. Fresh real vmlinux/exports, normalized config and release, strong decoder
   imports resolved against kernel/media/MDT/Venus export tables. The unchanged
   recipe independently performs normal strict MODPOST and existing BSP checks.
4. Actual existing BSP hardware payloads, ELF architectures and linked EGL/GLES/
   GBM probe. Packaged GPU release/APK identity matches the qualified video
   metadata. Base DT identities agree across audio/GPU/video packages. Actual
   packaged CPU/GPU/video helpers compose the packaged audio DT, preserving four
   CPUs and enabled GPU/audio; retain the resulting DT for review.
5. Source fixture hashes before and after, real normal-build return codes and
   package verification report. A graceful unsupported-video skip is a failed
   qualified-video gate. No transplanted binaries, false export metadata,
   `!check`, `--no-deps` or MODPOST warning/no-final bypass is used.

## Review and deployment boundaries

`workflow.yml` is a template under this candidate directory. Only after root
review should it be copied to a new experimental checkout's
`.github/workflows/m10-video-full-bsp.yml`, with these scripts and the exact small
fixture/manifest at the referenced repository paths. Keep the existing production
workflow and the running Chromium branch untouched. Dispatch the separate
workflow through the initial bounded push or a later manual dispatch; artifact success is a software-build gate, not production
qualification.

Still open after a successful run: full combined package lifecycle and actual
M10 boot-deploy/mkinitfs/systemd/loader ordering/recovery, target reboot and
official-kernel fallback, physical hardware regressions, paired userspace. The
successful GStreamer flushing seeks used a private deferred-release plugin;
installed stock GStreamer remains unpatched. Chromium playback/selection,
1080 visible-crop protocol, codec coverage and decode DVFS/power remain separate
gates. No new fixture source correction was made during this preparation.
