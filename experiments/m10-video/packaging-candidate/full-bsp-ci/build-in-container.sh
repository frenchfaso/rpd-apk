#!/bin/sh
# Fresh native ARM Alpine container only; unchanged recipes and throwaway key.
set -eu
if [ "$(uname -m)" != aarch64 ] || [ "${JOBS:-}" != 2 ] || [ "${GITHUB_ACTIONS:-}" != true ]; then
    printf '%s\n' 'Only the two-job native ARM CI builder may execute this recipe.' >&2
    exit 2
fi
unset KBUILD_MODPOST_WARN KBUILD_MODPOST_NOFINAL
apk add --no-cache alpine-sdk python3 py3-libfdt sudo kmod llvm22
mkdir -p /build /review
python3 /candidate/verify.py resources /build /review/container-resources.json || exit 1
python3 /candidate/verify.py inputs /fixture /fixture-manifest.json /review/input-proof.json --stage /build || exit 1
apk info -vv > /review/bootstrap-packages.txt
apk policy > /review/bootstrap-policy.txt
cat /etc/apk/repositories > /review/bootstrap-repositories.txt
sha256sum /usr/bin/abuild > /review/abuild-program.sha256
adduser -D builder
addgroup builder abuild
printf 'builder ALL=(root) NOPASSWD: /sbin/apk\n' > /etc/sudoers.d/m10-bsp-builder
export ABUILD_USERDIR=/home/builder/.abuild
export REPODEST=/home/builder/packages
export SRCDEST=/build/distfiles
export MAKEFLAGS=-j2
mkdir -p /home/builder/.abuild /home/builder/packages /build/distfiles
chown -R builder:builder /home/builder /build
su builder -c 'abuild-keygen -a -n'
# Retain genuine built sources/exports until the separate artifact audit. Normal
# abuild build/check/package/dependency cleanup still runs; no recipe override.
printf 'CLEANUP="bldroot pkgdir deps"\n' >> /home/builder/.abuild/abuild.conf
cp /home/builder/.abuild/*.pub /etc/apk/keys/
mkdir /review/keys /review/packages
cp /home/builder/.abuild/*.pub /review/keys/
printf '\n/home/builder/packages/ports\n' >> /etc/apk/repositories
for port in rpd-cpu-topology-m10 rpd-backlight-m10; do
    if [ "$port" = rpd-backlight-m10 ]; then
        # Normal signed dependency installation, retained before abuild's
        # standard final dependency cleanup. No prepare/check/build bypass.
        su builder -c 'cd /build/ports/rpd-backlight-m10 && abuild deps' > /review/full-sdk.log 2>&1
        apk info -vv > /review/full-sdk-packages.txt
        apk policy > /review/full-sdk-policy.txt
    fi
    printf '%s\n' "Starting normal abuild -r: $port"
    set +e
    su builder -c "cd /build/ports/$port && abuild -r" > "/review/$port.log" 2>&1
    result=$?
    set -e
    printf '%s\n' "$result" > "/review/$port.rc"
    cat "/review/$port.log"
    apk info -vv > "/review/after-$port-packages.txt"
    if [ "$result" -ne 0 ]; then exit "$result"; fi
    apk update
done
cp /home/builder/packages/ports/aarch64/*.apk /review/packages/
cp /home/builder/packages/ports/aarch64/APKINDEX.tar.gz /review/packages/
python3 /candidate/verify.py artifacts /fixture /build /review/packages /review/keys /review/artifact-proof.json || exit 1
sha256sum /review/packages/*.apk > /review/apk-sha256.txt
python3 /candidate/verify.py inputs /fixture /fixture-manifest.json /review/input-proof-after.json || exit 1
printf '%s\n' 'Full BSP normal build/check/package and artifact audit PASS; no boot/device qualification.' > /review/PASS.txt
# The parent runner removes this whole dedicated container even after failure.
