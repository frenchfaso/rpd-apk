#!/bin/sh
# Called from the exact, prepared pmOS kernel source directory.
set -eu
module="$srcdir/gpu-module"
mkdir -p "$module/drivers/media/cec" "$module/drivers/gpu" "$module/drivers/soc/qcom"
cp -a drivers/gpu/drm "$module/drivers/gpu/"
cp -a drivers/media/cec/core "$module/drivers/media/cec/"
cp -a drivers/media/rc "$module/drivers/media/"
cp drivers/soc/qcom/ubwc_config.c drivers/soc/qcom/mdt_loader.c "$module/drivers/soc/qcom/"
for name in 0001-adreno-504-bringup 0002-a5xx-gpmu-registers 0003-adreno-504-rpm-domain; do
    patch -d "$module" -p1 < "$srcdir/$name.diff"
done
printf '%s\n' 'obj-m += drm_exec.o drm_gpuvm.o' 'obj-m += scheduler/ display/ msm/' > "$module/drivers/gpu/drm/Makefile"
printf '%s\n' 'obj-m += mdt_loader.o ubwc_config.o' > "$module/drivers/soc/qcom/Makefile"
printf '%s\n' 'obj-m += drivers/media/rc/ drivers/media/cec/core/ drivers/soc/qcom/ drivers/gpu/drm/' > "$module/Makefile"
make LLVM=1 -j2 M="$module" modules
