# Mesa for Adreno 504

Based on Alpine aports main/mesa at `5be9d1d4593ed639fe9e1905cee3a791de36bff3`.
The upstream build options and subpackages are preserved, including llvmpipe.
Local changes: aarch64 only, package revision offset 1000, and five patches:

- Recognize Adreno 504 in the existing small-A5xx family.
- Count depth/stencil MSAA samples once when sizing GMEM tiles. The old
  calculation can loop indefinitely on a 136 KiB GPU with 4x MSAA.
- Prefer rendering directly to system memory on A504. Complex Three.js scenes
  otherwise accumulate a large GPU queue and can stall Chromium and labwc.
  Other GPUs retain their existing selection; forced GMEM remains available
  for diagnosis. A5xx does not expose multisampled-render-to-texture.
- Use the generic clear path on A504. Standard CTS fragment-operation tests
  expose stale pixels with fast clears in bypass; all 100 cases in that group
  pass with the generic path.
- Tile A504 depth/stencil textures while retaining linear color resources.
  This fixes CTS zero-to-one depth-texture readback. Targeted GLES2/GLES3
  regression gives 1,463 distinct passes, 91 unsupported and zero failures,
  including all 432 GLES3 shadow tests. General texture tiling fails the
  fragment tests and remains disabled.

The bypass policy is under qualification; do not publish the GPU integration
until the standard suites and physical desktop/recovery checks pass. The new
clear and depth-layout changes have passed only targeted CTS groups so far;
full-suite qualification is incomplete. Forced-linear/shared depth resources
still need verification. The diagnostic build is isolated; installed Mesa
remains unchanged.

Validated on TB-X505L with GLES2/GLES3 and 4x MSAA pixel readback, Chromium
WebGL 1/2 and the physical labwc greeter. This is not a conformance claim.
Kernel upgrades remain independent; software rendering remains available.

A broader GLES2 run subsequently hit a GPU command-processor fault after more
than 7,000 reported passes. The run was stopped and its last CTS case/group
saved for isolated reproduction. This remains a release blocker; the targeted
passes do not establish driver stability.
