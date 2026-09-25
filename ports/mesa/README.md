# Mesa for Adreno 504

Based on Alpine aports main/mesa at `5be9d1d4593ed639fe9e1905cee3a791de36bff3`.
The upstream build options and subpackages are preserved, including llvmpipe.
Local changes: aarch64 only, package revision offset 1000, and three patches:

- Recognize Adreno 504 in the existing small-A5xx family.
- Count depth/stencil MSAA samples once when sizing GMEM tiles. The old
  calculation can loop indefinitely on a 136 KiB GPU with 4x MSAA.
- Prefer rendering directly to system memory on A504. Complex Three.js scenes
  otherwise accumulate a large GPU queue and can stall Chromium and labwc.
  Other GPUs retain their existing selection; forced GMEM remains available
  for diagnosis. A5xx does not expose multisampled-render-to-texture.

The bypass policy is under qualification; do not publish the GPU integration
until the physical desktop and recovery checks pass.

Validated on TB-X505L with GLES2/GLES3 and 4x MSAA pixel readback, Chromium
WebGL 1/2 and the physical labwc greeter. This is not a conformance claim.
Kernel upgrades remain independent; software rendering remains available.
