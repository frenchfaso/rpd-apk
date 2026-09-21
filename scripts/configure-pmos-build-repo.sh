#!/bin/sh
# Build/test container only; never installed on an end-user device.
set -eu
cd "$(dirname "$0")/.."
cp keys/build.postmarketos.org.rsa.pub /etc/apk/keys/
line='@pmos https://mirror.postmarketos.org/postmarketos/main'
grep -qxF "$line" /etc/apk/repositories || printf '%s\n' "$line" >> /etc/apk/repositories
