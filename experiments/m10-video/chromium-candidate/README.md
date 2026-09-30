# Chromium V4L2 candidate, 2026-09-30

Status: source-reviewed, unbuilt candidate. Native Venus decode qualification is
separate evidence; this candidate does not establish Chromium browser support.
No production recipe, workflow, VM or device was changed.

The two patches are:

- `patches/chromium-linux-v4l2-decoder-broker.patch`: 33 added lines in three
  Chromium files. A small static helper returns paths from the existing
  `V4L2Device` discovery/classification code. Before GPU sandbox entry,
  `AddV4L2GpuPermissions` allows read/write access only to those accepted decoder
  paths on generic Linux. Discovery still uses `/dev/video0` through
  `/dev/video255`; no device-specific aliases are needed. The classifier requires
  compressed-video OUTPUT and raw CAPTURE formats, excluding capture-only
  cameras. It closes every probe FD. No seccomp rule or directory-wide access is
  added. ChromeOS/Chromecast paths retain their existing behavior.
- `patches/alpine-chromium-enable-v4l2-aarch64.patch`: adds the source patch and
  its SHA-512 to the Alpine recipe, enables `use_v4l2_codec` on aarch64 while
  retaining VA-API, and increments the experimental package revision to r2.
  `prepared/aports/community/chromium` contains the resulting recipe and source
  patch, not the complete Alpine port and all its existing auxiliary files.

Both are pinned to Chromium `152.0.7977.82`, commit
`d04cdb24d67b081f6cf80200ffc5233f44b61109`, and Alpine aports commit
`a44854115ef1a1cda0c41b3e6f0974f51755d736` (`152.0.7977.82-r1`). The exact upstream,
prepared and reference file hashes are in `source-manifest.json`. The recipe
matches the previously saved project recipe byte for byte. This is a candidate
revision, not a published replacement for Alpine Chromium.

Validation: `python3 prepare.py` regenerates the diff, recipe and manifest;
`python3 validate.py` verifies retained hashes, applies both patches with
`patch -F0` without offsets, compares the result byte for byte with the prepared
files, checks recipe syntax with `sh -n`, and checks the recipe's patch checksum.
Results are retained in `validation.json`. The pinned `content/common/BUILD.gn`
already adds `//media/gpu/v4l2` when enabled, so the new helper needs no GN
dependency change. The inspected Alpine musl sandbox patches touch other files.
Complete Alpine/copium preparation, GN generation and C++ compilation remain
required. Independent source review by task `m10_display_clock_research` found
no correctness blocker; that review did not execute Chromium or its sandbox.

The permission list is a startup snapshot. Load the decoder before Chromium
starts; later devices need a GPU process/browser restart. Path approval does not
pin a device's identity across later privileged node replacement. OOP video
decoding remains at the Linux default, disabled: its separate sandbox uses
ChromeOS-style aliases and is outside this candidate. Hardware encoding and
image-processor access are outside the candidate's qualification.

For a reviewed dual-backend build, the manual test selector is:

```sh
chromium --enable-features=AcceleratedVideoDecoder,PreferV4L2VideoAcceleration
```

`AcceleratedVideoDecoder` is the actual feature string. The GL and Linux
zero-copy GL feature flags already default enabled. Stateful H264 selection is
automatic from OUTPUT formats; no `PlatformVideoDecoder` or stateless-decoder
flag is required. Preserve the normal sandbox and graphics configuration during
qualification. Require `V4L2VideoDecoder` in `chrome://media-internals`, actual
rendered playback, clean EOF/seek/repeated sessions and suspend/resume. The
NV12 path additionally needs successful `VIDIOC_EXPBUF` and EGL DMA-BUF native
pixmap import; Chromium checks `supports_nv12_gl_native_pixmap`. Its V4L2
direct-allocation path still has a full-browser-test TODO. Standard runner CI can
compile/package this path but cannot prove native Venus decoding or rendering.

Primary sources:

- [Pinned Alpine recipe](https://github.com/alpinelinux/aports/blob/a44854115ef1a1cda0c41b3e6f0974f51755d736/community/chromium/APKBUILD)
- [Chromium GN defaults](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/gpu/args.gni)
- [Runtime selectors](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/base/media_switches.cc)
- [Existing device classifier](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/gpu/v4l2/v4l2_device.cc)
- [GPU broker setup](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/content/common/gpu_pre_sandbox_hook_linux.cc)
- [Rendering requirements](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/mojo/services/gpu_mojo_media_client_linux.cc)
- [Direct V4L2 allocation route](https://chromium.googlesource.com/chromium/src/+/152.0.7977.82/media/gpu/chromeos/video_decoder_pipeline.cc)

See `build-notes.md` for the runner gate. The GStreamer seek qualification
reported by the parent task is separate from this browser candidate and remains
under investigation.
