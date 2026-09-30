#!/bin/sh
# Retain the pinned recipe's normal policy for its unchanged upstream patches.
# Only our two candidate patches require zero-fuzz, noninteractive application.
set -eu
strict=0
input_next=0
for argument in "$@"; do
    if [ "$input_next" = 1 ]; then
        case "${argument##*/}" in
            alpine-chromium-enable-v4l2-aarch64.patch|chromium-linux-v4l2-decoder-broker.patch) strict=1;;
        esac
        input_next=0
    fi
    case "$argument" in
        -i|--input) input_next=1;;
        --input=*)
            filename=${argument#--input=}
            case "${filename##*/}" in
                alpine-chromium-enable-v4l2-aarch64.patch|chromium-linux-v4l2-decoder-broker.patch) strict=1;;
            esac;;
    esac
done
if [ "$strict" = 1 ]; then
    exec /usr/bin/patch "$@" --fuzz=0 --batch
fi
exec /usr/bin/patch "$@"
