# Bookshelf portability and cover cache

`rpd-bookshelf` keeps Raspberry Pi Bookshelf's catalogue and download behaviour.
Two independent patches avoid the GNU `df` dependency (`fstatvfs` on the open
download destination) and cache scaled cover images.

## Thumbnail cache

`0003-thumbnail-cache.patch` changes only `get_cover()` in `src/rp_bookshelf.c`.
It follows the surrounding C style and adds no library dependencies. PNGs live in
`$XDG_CACHE_HOME/bookshelf/thumbnails` (normally `~/.cache/bookshelf/thumbnails`).
Each source path has one SHA-256-named entry. PNG metadata records the source
modification time, file size and `COVER_SIZE`; mismatches regenerate the image.
Scaling and interpolation are unchanged. Like common thumbnail caches, timestamp
validation uses seconds: an edit preserving both timestamp and size is not detected.

Images are saved atomically through GLib before status overlays are applied.
Missing/corrupt entries or unavailable cache storage fall back to the original
loader. Missing/unreadable source images use the existing placeholder without
caching it as a cover. No PDFs, original covers or catalogue files are removed.
The cache is disposable; deleting its `thumbnails` directory rebuilds it next time.

The first load pays for PNG encoding. Later loads still decode small PNGs, but skip
original image decoding and resizing. This does not remove network catalogue
updates or GTK/software-rendering overhead.

## Verification

`tests/verify_bookshelf_cache.py` compiles the actual patched function and checks
pixel parity for portrait, landscape, RGB/RGBA and already-sized covers; cache
hits without original-image decoding; independent mutable pixbufs; unchanged
cache files on hits; timestamp/size invalidation; corrupt or metadata-free PNGs;
unwritable cache paths; and missing/corrupt original images.

The test runs in the APK build pipeline. Its synthetic fixtures opt out of Glycin's
nested sandbox only inside the test process for container compatibility. The
installed application retains normal image-loader sandboxing. The same binary
also passed on M10 with sandboxing enabled.

M10 measurement (2026-09-23, 185 existing covers, loader only):

| Run | Time |
| --- | ---: |
| Original loader | 2.439 s / 2.125 s |
| Create thumbnail cache | 6.231 s |
| Reuse thumbnail cache | 1.838 s / 1.636 s |

The extra cache occupied about 5.1 MiB. These are small sequential samples, not
whole-application launch benchmarks. Full application checks also confirmed
185 generated entries and normal covers/status overlays.

## Upstream contribution preparation

Upstream: <https://github.com/raspberrypi-ui/bookshelf>, inspected at
`8d837571ef02a4c1c4d74e419ebc59d66b47b685` on 2026-09-23.
The public tree and community profile contain no CONTRIBUTING file, code style
file, PR template or documented CLA/DCO requirement. No public default `.github`
repository was found for `raspberrypi-ui` or `raspberrypi`. The upstream README
provides Meson build instructions; retain the existing BSD-3-Clause notices.
Rules for other Raspberry Pi projects are not assumed to apply to Bookshelf.

The cache patch applies independently to upstream master and does not include
Alpine packaging, the separate statvfs fix or M10-specific changes. No upstream
issue or pull request has been submitted. An eventual contribution should include
the cache behaviour, test results and modest measured performance gain; Debian /
Raspberry Pi OS validation remains separate from our Alpine/M10 checks.
