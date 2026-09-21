#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
sh scripts/configure-pmos-build-repo.sh
cp keys/rpd-apk.rsa.pub /etc/apk/keys/
# This clean signing container has official Alpine keys plus our production key,
# never the build job's throwaway key.
for pkg in out/aarch64/*.apk; do apk verify "$pkg"; done
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apk/keys"
cp /etc/apk/keys/*.pub "$root/etc/apk/keys/"
cp /etc/apk/repositories "$root/etc/apk/repositories"
printf '\n%s/out\n' "$PWD" >> "$root/etc/apk/repositories"
apk --root "$root" --initdb --no-scripts add linux-postmarketos-qcom-msm89x7@pmos rpd-desktop-m10
printf 'Production signatures and clean-root installation passed\n' >> out/validation.txt
