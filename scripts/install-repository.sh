#!/bin/sh
# Configure the repository only; does not install a desktop or change boot.
set -eu
[ "$(id -u)" = 0 ] || { echo "Run this script as root" >&2; exit 1; }
[ "$(apk --print-arch)" = aarch64 ] || { echo "Only aarch64 is published" >&2; exit 1; }
url=https://frenchfaso.github.io/rpd-apk
keydir=$(mktemp -d)
trap 'rm -rf "$keydir"' EXIT
wget -q -O "$keydir/rpd-apk.rsa.pub" "$url/rpd-apk.rsa.pub"
printf 'fc384ed522d75a810aa1670ed3e52f7f0c3a4f66ff1761e4fd704b937f1f7ed2  %s/rpd-apk.rsa.pub\n' "$keydir" | sha256sum -c -
install -Dm644 "$keydir/rpd-apk.rsa.pub" /etc/apk/keys/rpd-apk.rsa.pub
if ! grep -qxF "$url" /etc/apk/repositories; then
    printf '\n%s\n' "$url" >> /etc/apk/repositories
fi
apk update
printf 'Repository configured. Install with: apk add rpd-desktop-m10\n'
