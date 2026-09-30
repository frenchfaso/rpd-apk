#!/bin/sh
# Disposable native Alpine runner only. No production key, deployment or device.
set -eu
candidate=/candidate
review=/review
work=/build
jobs=${JOBS:-4}
full=${FULL_RECIPE:-0}
case "$jobs" in 1|2|3|4) ;; *) echo 'JOBS must be 1..4' >&2; exit 2;; esac
case "$full" in 0|1) ;; *) echo 'FULL_RECIPE must be 0 or 1' >&2; exit 2;; esac
test "$(uname -m)" = aarch64
apk add --no-cache alpine-sdk bash curl patch python3 sudo tar time
mkdir -p "$work" "$review"
python3 "$candidate/ci/verify-build.py" resources "$work" "$review/container-resources.json"
python3 "$candidate/ci/verify-build.py" inputs "$candidate" "$review/candidate-inputs.json"
apk info -vv > "$review/bootstrap-packages.txt"
cat /etc/apk/repositories > "$review/alpine-repositories.txt"
cat /etc/alpine-release > "$review/alpine-release.txt"
adduser -D builder
addgroup builder abuild
printf 'builder ALL=(root) NOPASSWD: /sbin/apk\n' > /etc/sudoers.d/chromium-builder
mkdir -p /home/builder/.abuild /home/builder/packages "$work/sources" "$work/tools"
chown -R builder:builder /home/builder "$work" "$review"
export ABUILD_USERDIR=/home/builder/.abuild
su builder -c 'abuild-keygen -a -n'
cp /home/builder/.abuild/*.pub /etc/apk/keys/
# Force zero fuzz in normal Alpine/copium preparation. Bound every recipe Ninja
# invocation, including its full build(), without replacing recipe functions.
cat > "$work/tools/patch" <<'SH'
#!/bin/sh
exec /usr/bin/patch "$@" --fuzz=0 --batch
SH
cat > "$work/tools/ninja" <<'SH'
#!/bin/sh
exec /usr/bin/ninja -j "$JOBS" "$@"
SH
chmod 755 "$work/tools/patch" "$work/tools/ninja"
export JOBS="$jobs" FULL_RECIPE="$full" MAKEFLAGS="-j$jobs"
export PATH="$work/tools:$PATH" SRCDEST="$work/sources" REPODEST=/home/builder/packages
export CANDIDATE_DIR="$candidate" REVIEW_DIR="$review" WORK_DIR="$work"
su builder -s /bin/sh <<'SH'
set -eu
export PATH="$WORK_DIR/tools:$PATH"
test "$(command -v ninja)" = "$WORK_DIR/tools/ninja"
test "$(command -v patch)" = "$WORK_DIR/tools/patch"
pin=a44854115ef1a1cda0c41b3e6f0974f51755d736
cd "$WORK_DIR"
curl --fail --location --retry 3 --output aports.tar.gz "https://codeload.github.com/alpinelinux/aports/tar.gz/$pin"
sha256sum aports.tar.gz > "$REVIEW_DIR/aports-archive.sha256"
mkdir aports
tar -xzf aports.tar.gz -C aports --strip-components=1 "aports-$pin/community/chromium"
port="$WORK_DIR/aports/community/chromium"
python3 "$CANDIDATE_DIR/ci/verify-build.py" stage "$port" "$REVIEW_DIR/recipe-stage.json" --candidate "$CANDIDATE_DIR"
cd "$port"
abuild deps
apk info -vv > "$REVIEW_DIR/build-packages.txt"
abuild fetch verify unpack prepare
source_dir="$port/src/chromium-152.0.7977.82"
test -d "$source_dir/out/bld"
python3 "$CANDIDATE_DIR/ci/verify-build.py" prepared "$source_dir" "$REVIEW_DIR/prepared-source.json" --candidate "$CANDIDATE_DIR"
python3 "$CANDIDATE_DIR/ci/verify-build.py" targets "$source_dir" "$REVIEW_DIR/compiled-units.json" > "$REVIEW_DIR/ninja-targets.txt"
set --
while IFS= read -r target; do set -- "$@" "$target"; done < "$REVIEW_DIR/ninja-targets.txt"
test "$#" -eq 2
/usr/bin/time -v ninja -C "$source_dir/out/bld" "$@" 2> "$REVIEW_DIR/unit-build-time.txt"
python3 "$CANDIDATE_DIR/ci/verify-build.py" completed "$source_dir" "$REVIEW_DIR/compiled-units.json"
if [ "$FULL_RECIPE" = 1 ]; then
    # Normal build/check/package/sign-with-throwaway-key sequence. No !check or
    # checksum/prepare bypass. abuild -r cleans src, then unpacks/prepares again;
    # the two proven objects are intentionally rebuilt on that normal path.
    /usr/bin/time -v abuild -r 2> "$REVIEW_DIR/full-recipe-time.txt"
    mkdir "$REVIEW_DIR/packages"
    find /home/builder/packages -type f -name '*.apk' -exec cp '{}' "$REVIEW_DIR/packages/" ';'
    test -n "$(find "$REVIEW_DIR/packages" -name '*.apk' -print -quit)"
    sha256sum "$REVIEW_DIR"/packages/*.apk > "$REVIEW_DIR/package-sha256.txt"
    cp /home/builder/.abuild/*.pub "$REVIEW_DIR/packages/"
    printf '%s\n' 'Normal abuild -r passed; ephemeral signatures only; no browser/device qualification.' > "$REVIEW_DIR/full-recipe-PASS.txt"
fi
SH
