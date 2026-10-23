#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
cp keys/rpd-apk.rsa.pub keys/build.postmarketos.org.rsa.pub /etc/apk/keys/
printf '\nhttps://mirror.postmarketos.org/postmarketos/extra-repos/systemd/main\n' >> /etc/apk/repositories
# This clean signing container has official Alpine keys plus our production key,
# never the build job's throwaway key.
for pkg in out/aarch64/*.apk; do apk verify "$pkg"; done
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apk/keys"
cp /etc/apk/keys/*.pub "$root/etc/apk/keys/"
cp /etc/apk/repositories "$root/etc/apk/repositories"
printf '\n%s/out\n' "$PWD" >> "$root/etc/apk/repositories"
apk --root "$root" --initdb --no-scripts add rpd-desktop-m10 systemd polkit-systemd squeekboard-systemd
sh scripts/verify-security-runtime.sh "$root" > out/production-security-runtime.json
printf 'Production signatures and clean-root installation passed\n' >> out/validation.txt
