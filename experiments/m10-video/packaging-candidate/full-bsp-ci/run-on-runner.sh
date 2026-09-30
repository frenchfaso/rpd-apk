#!/usr/bin/env bash
# GitHub Linux ARM runner only; no local Podman/Mac/source build.
set -euo pipefail
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_OS:-} != Linux || ${RUNNER_ARCH:-} != ARM64 ]]; then
    printf '%s\n' 'Only a GitHub Linux ARM64 runner may execute this build.' >&2
    exit 2
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    printf '%s\n' 'Native Linux aarch64 required.' >&2
    exit 2
fi
candidate=${1:?candidate directory}
fixture=${2:?exact source fixture}
manifest=${3:?exact fixture manifest}
review=${4:?fresh owned artifact directory}
if [[ -e $review ]]; then
    printf '%s\n' 'Review directory must be fresh.' >&2
    exit 2
fi
mkdir -p "$review"
candidate=$(realpath "$candidate")
fixture=$(realpath "$fixture")
manifest=$(realpath "$manifest")
review=$(realpath "$review")
python3 "$candidate/verify.py" resources "$review" "$review/host-resources.json" || exit 1
python3 "$candidate/verify.py" inputs "$fixture" "$manifest" "$review/host-input-proof.json" || exit 1
printf '%s\n' "${GITHUB_SHA:?}" > "$review/checkout-commit.txt"
container="m10-full-bsp-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
image=alpine@sha256:020dfcbaaf4cc1078bf2d9c7ba31a8466e334061dcd2f248001d68f79e52c000
logger=
sampler=
cleanup() {
    result=$?
    trap - EXIT INT TERM
    docker stop --time 10 "$container" >/dev/null 2>&1 || true
    if [[ -n $logger ]]; then wait "$logger" || true; fi
    if [[ -n $sampler ]]; then kill "$sampler" 2>/dev/null || true; wait "$sampler" || true; fi
    docker inspect "$container" > "$review/container-final.json" 2>/dev/null || true
    docker rm -f "$container" > "$review/container-cleanup.txt" 2>&1 || true
    printf '%s\n' "$result" > "$review/runner-exit.txt"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker pull "$image"
docker image inspect "$image" > "$review/image-identity.json"
docker run --name "$container" --detach --cpus=2 --memory=12g --memory-swap=14g \
    --mount "type=bind,source=$candidate,target=/candidate,readonly" \
    --mount "type=bind,source=$fixture,target=/fixture,readonly" \
    --mount "type=bind,source=$manifest,target=/fixture-manifest.json,readonly" \
    --mount "type=bind,source=$review,target=/review" \
    --env GITHUB_ACTIONS=true --env JOBS=2 \
    "$image" sh /candidate/build-in-container.sh > "$review/container-id.txt"
docker logs --follow "$container" 2>&1 | tee "$review/container.log" &
logger=$!
(
    monitor_exit() {
        result=$?
        trap - EXIT
        if [[ $result != 0 ]]; then
            printf '%s\n' "$result" > "$review/resource-monitor-failure.txt"
            docker stop --time 30 "$container" || true
        fi
        exit "$result"
    }
    trap monitor_exit EXIT
    while :; do
        running=$(docker inspect -f '{{.State.Running}}' "$container")
        [[ $running == true ]] || break
        date -u +'%Y-%m-%dT%H:%M:%SZ'
        df -B1 "$review"
        free -b
        docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}} {{.BlockIO}}' "$container"
        free_bytes=$(df -B1 --output=avail "$review" | tail -1 | tr -d ' ')
        writable_bytes=$(docker inspect --size -f '{{.SizeRw}}' "$container")
        printf 'writable_layer_bytes=%s\n' "$writable_bytes"
        if (( free_bytes < 8 * 1024**3 || writable_bytes > 12 * 1024**3 )); then
            printf '%s\n' 'Resource floor/cap breached; stopping owned container.' > "$review/resource-stop.txt"
            docker stop --time 30 "$container"
            break
        fi
        sleep 15
    done
) > "$review/resource-samples.txt" 2>&1 &
sampler=$!
set +e
timeout --signal=TERM --kill-after=60s 180m docker wait "$container" > "$review/container-exit.txt"
wait_rc=$?
set -e
if [[ $wait_rc != 0 ]]; then exit "$wait_rc"; fi
container_rc=$(cat "$review/container-exit.txt")
if [[ ! $container_rc =~ ^[0-9]+$ ]]; then exit 1; fi
if wait "$logger"; then
    logger_rc=0
else
    logger_rc=$?
fi
logger=
printf '%s\n' "$logger_rc" > "$review/logger-exit.txt"
if (( logger_rc != 0 )); then exit "$logger_rc"; fi
wait "$sampler" || exit 1
sampler=
if [[ -f $review/resource-stop.txt || -f $review/resource-monitor-failure.txt || $container_rc != 0 ||
      ! -f $review/PASS.txt || ! -f $review/artifact-proof.json ]]; then
    exit 1
fi
