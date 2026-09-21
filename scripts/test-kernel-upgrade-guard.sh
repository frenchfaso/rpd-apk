#!/bin/sh
# Deliberately unsigned synthetic packages in an isolated throwaway APK root.
# Never runs against / or a device; tests solver semantics, not authenticity.
set -eu
testroot=$(mktemp -d)
trap 'rm -rf "$testroot"' EXIT
mkdir -p "$testroot/repo" "$testroot/root" "$testroot/empty"
makepkg() {
    name=$1 version=$2 dependency=${3:-}
    if [ -n "$dependency" ]; then
        apk mkpkg --files "$testroot/empty" --info "name:$name" --info "version:$version" --info 'arch:aarch64' --info "depends:$dependency" --output "$testroot/repo/$name-$version.apk"
    else
        apk mkpkg --files "$testroot/empty" --info "name:$name" --info "version:$version" --info 'arch:aarch64' --output "$testroot/repo/$name-$version.apk"
    fi
}
index() { apk --allow-untrusted mkndx --output "$testroot/repo/index.adb" "$testroot"/repo/*.apk; }
runapk() { apk --root "$testroot/root" --arch aarch64 --repositories-file /dev/null --repository "$testroot/repo/index.adb" --allow-untrusted --no-cache "$@"; }
makepkg test-kernel 1.0-r0
makepkg test-backlight 1.0-r0 test-kernel=1.0-r0
index
runapk --initdb add --no-scripts test-kernel test-backlight
makepkg test-kernel 1.0-r1
# Rolling repositories can remove the old kernel; the installed pair must survive.
rm "$testroot/repo/test-kernel-1.0-r0.apk"
index
# Either retaining the pair or reporting a conflict is valid; no mismatch is.
runapk upgrade --no-scripts || true
runapk info -e test-kernel=1.0-r0
makepkg test-backlight 1.0-r1 test-kernel=1.0-r1
index
runapk upgrade --no-scripts
runapk info -e test-kernel=1.0-r1
runapk info -e test-backlight=1.0-r1
printf '%s\n' 'Kernel upgrade guard passed: unmatched kernel held; matched pair upgraded.'
