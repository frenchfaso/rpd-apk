#!/bin/sh
# Called from the exact, prepared pmOS kernel source directory.
set -eu

# Only skip an upstream backport when the exact reverse patch applies.
# A changed kernel context must fail the optional module build, not silently
# produce a module with an unknown mix of recovery fixes.
apply_upstream_patch() {
    if patch --dry-run --batch --forward --fuzz=0 -d "$module" -p1 \
        < "$srcdir/$1.diff" >/dev/null 2>&1; then
        patch --batch --forward --fuzz=0 -d "$module" -p1 < "$srcdir/$1.diff"
    elif patch --dry-run --batch --reverse --force --fuzz=0 -d "$module" -p1 \
        < "$srcdir/$1.diff" >/dev/null 2>&1; then
        printf '%s\n' "rpd-gpu-m10: $1 already applied upstream"
    else
        printf '%s\n' "rpd-gpu-m10: cannot apply or verify $1; refusing this module build" >&2
        return 1
    fi
}

module="$srcdir/gpu-module"
mkdir -p "$module/drivers/media/cec" "$module/drivers/gpu" "$module/drivers/soc/qcom"
cp -a drivers/gpu/drm "$module/drivers/gpu/"
cp -a drivers/media/cec/core "$module/drivers/media/cec/"
cp -a drivers/media/rc "$module/drivers/media/"
cp drivers/soc/qcom/ubwc_config.c drivers/soc/qcom/mdt_loader.c "$module/drivers/soc/qcom/"
for name in 0001-adreno-504-bringup 0002-a5xx-gpmu-registers 0003-adreno-504-rpm-domain 0004-a504-retained-gx-reset; do
    patch -d "$module" -p1 < "$srcdir/$name.diff"
done
for name in 0005-msm-recover-before-retire 0006-msm-recovery-task-ref; do
    apply_upstream_patch "$name"
done
# Board power ordering and GPU teardown ownership fixes, in reviewed order.
for name in 0007-a504-physical-cx-device-link 0008-msm-gpu-only-remove-private 0009-a5xx-release-shadow-mapping 0010-a504-bounded-fragment-progress; do
    patch --batch --forward --fuzz=0 -d "$module" -p1 < "$srcdir/$name.diff"
done
printf '%s\n' 'obj-m += drm_exec.o drm_gpuvm.o' 'obj-m += scheduler/ display/ msm/' > "$module/drivers/gpu/drm/Makefile"
printf '%s\n' 'obj-m += mdt_loader.o ubwc_config.o' > "$module/drivers/soc/qcom/Makefile"
printf '%s\n' 'obj-m += drivers/media/rc/ drivers/media/cec/core/ drivers/soc/qcom/ drivers/gpu/drm/' > "$module/Makefile"
make LLVM=1 -j2 M="$module" modules
