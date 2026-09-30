#!/usr/bin/env python3
"""Small, strict checks for the disposable native Chromium build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

APORTS = "a44854115ef1a1cda0c41b3e6f0974f51755d736"
BASE_RECIPE = "11eaf1455db582568e715bb161e4b890618977accf65ac3d89f6f4373bed8252"
UNITS = ("content/common/gpu_pre_sandbox_hook_linux.cc", "media/gpu/v4l2/v4l2_device.cc")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT)


def inputs(candidate):
    manifest = json.loads((candidate / "source-manifest.json").read_text())
    require(manifest["aports_commit"] == APORTS, "aports pin changed")
    require(manifest["chromium_version"] == "152.0.7977.82", "Chromium version changed")
    require(manifest["chromium_commit"] == "d04cdb24d67b081f6cf80200ffc5233f44b61109",
            "Chromium commit changed")
    upstream = {item["path"]: item["sha256"] for item in manifest["upstream_sources"]}
    require(upstream["upstream/aports/community/chromium/APKBUILD"] == BASE_RECIPE,
            "base recipe pin changed")
    for group in (upstream, manifest["patches"], manifest["prepared_files"]):
        for name, expected in group.items():
            require(sha(candidate / name) == expected, "candidate input changed: " + name)
    return manifest


def assess_resources(architecture, cpus, ram, swap, free):
    report = {"architecture": architecture, "cpus": cpus,
              "ram_bytes": ram, "swap_bytes": swap, "free_disk_bytes": free,
              "minimum_disk_bytes": 100 * 2**30, "minimum_ram_bytes": 14 * 2**30,
              "minimum_ram_plus_swap_bytes": 17 * 2**30}
    checks = {"native_aarch64": architecture == "aarch64", "four_cpus": cpus >= 4,
              "100_gib_free": free >= report["minimum_disk_bytes"],
              "14_gib_ram": ram >= report["minimum_ram_bytes"],
              "17_gib_ram_plus_swap": ram + swap >= report["minimum_ram_plus_swap_bytes"]}
    report.update(checks=checks, status="PASS" if all(checks.values()) else "FAIL")
    return report


def resources(directory):
    meminfo = dict(re.findall(r"^(\w+):\s+(\d+) kB$", Path("/proc/meminfo").read_text(), re.M))
    ram, swap = (int(meminfo[name]) * 1024 for name in ("MemTotal", "SwapTotal"))
    limit = Path("/sys/fs/cgroup/memory.max")
    if limit.is_file() and limit.read_text().strip() != "max":
        ram = min(ram, int(limit.read_text().strip()))
    limit = Path("/sys/fs/cgroup/memory.swap.max")
    if limit.is_file() and limit.read_text().strip() != "max":
        swap = min(swap, int(limit.read_text().strip()))
    cpus = os.cpu_count() or 0
    limit = Path("/sys/fs/cgroup/cpu.max")
    if limit.is_file():
        quota, period = limit.read_text().split()
        if quota != "max":
            cpus = min(cpus, int(quota) // int(period))
    fs = os.statvfs(directory)
    free = fs.f_bavail * fs.f_frsize
    return assess_resources(platform.machine(), cpus, ram, swap, free)


def stage(candidate, port):
    manifest = inputs(candidate)
    require(sha(port / "APKBUILD") == BASE_RECIPE, "downloaded APKBUILD differs from exact pin")
    recipe_patch = candidate / "patches/alpine-chromium-enable-v4l2-aarch64.patch"
    result = run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(recipe_patch)], port.parents[1])
    require(not re.search(r"fuzz|offset|FAILED|reversed", result, re.I), "non-exact recipe patch")
    broker = candidate / "patches/chromium-linux-v4l2-decoder-broker.patch"
    shutil.copyfile(broker, port / broker.name)
    for name in ("APKBUILD", broker.name):
        expected = manifest["prepared_files"]["prepared/aports/community/chromium/" + name]
        require(sha(port / name) == expected, "staged recipe input differs: " + name)
    return {"status": "PASS", "aports_commit": APORTS, "recipe_patch_apply": result,
            "staged_recipe_sha256": sha(port / "APKBUILD"), "broker_sha256": sha(broker)}


def prepared(candidate, source):
    manifest = inputs(candidate)
    checked = {}
    for name, expected in manifest["prepared_files"].items():
        if name.startswith("prepared/chromium/"):
            relative = name.removeprefix("prepared/chromium/")
            actual = sha(source / relative)
            require(actual == expected, "normal Alpine preparation changed candidate source: " + relative)
            checked[relative] = actual
    return {"status": "PASS", "prepared_source_sha256": checked}


def select_targets(text, source, query):
    selected = []
    for unit in UNITS:
        basename = Path(unit).stem + ".o"
        matches = []
        for line in text.splitlines():
            target = line.split(":", 1)[0]
            if target.endswith("/" + basename):
                detail = query(target)
                if re.search(r"(?:^|\s)(?:\.\./)+" + re.escape(unit) + r"(?:\s|$)", detail):
                    matches.append((target, detail))
        require(len(matches) == 1, "missing or ambiguous generated object target for " + unit)
        target, detail = matches[0]
        require(re.fullmatch(r"[A-Za-z0-9_./-]+", target) is not None, "unexpected Ninja target syntax")
        selected.append({"source": unit, "target": target, "query": detail})
    return selected


def targets(source):
    output = source / "out/bld"
    flags = {}
    for name, expected in (("target_cpu", '"arm64"'), ("use_v4l2_codec", "true"), ("use_vaapi", "true")):
        text = run(["gn", "args", str(output), "--list=" + name, "--short"], source)
        require(re.search(r"^" + name + r"\s*=\s*" + re.escape(expected) + r"\s*$", text, re.M),
                "wrong generated GN argument: " + name)
        flags[name] = expected
    text = run(["ninja", "-C", str(output), "-t", "targets", "all"])
    selected = select_targets(text, source,
                              lambda target: run(["ninja", "-C", str(output), "-t", "query", target]))
    return {"status": "PASS", "gn_arguments": flags, "objects": selected}


def completed(source, report):
    data = json.loads(report.read_text())
    for row in data["objects"]:
        path = source / "out/bld" / row["target"]
        require(path.is_file() and path.stat().st_size > 0, "compiled object missing: " + row["target"])
        row.update(bytes=path.stat().st_size, sha256=sha(path))
    header = source / "out/bld/gen/media/gpu/buildflags.h"
    text = header.read_text()
    for flag in ("USE_V4L2_CODEC", "USE_VAAPI"):
        require(re.search(r"BUILDFLAG_INTERNAL_" + flag + r"\(\)\s+\(1\)", text),
                "generated backend buildflag absent: " + flag)
    data.update(status="PASS", scope="Two modified C++ objects compiled; no final link or browser execution",
                generated_buildflags_sha256=sha(header))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("resources", "inputs", "stage", "prepared", "targets", "completed"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    if args.operation == "resources":
        data = resources(args.directory)
    elif args.operation == "inputs":
        inputs(args.directory)
        data = {"status": "PASS", "scope": "Retained candidate inputs only"}
    elif args.operation == "stage":
        data = stage(args.candidate, args.directory)
    elif args.operation == "prepared":
        data = prepared(args.candidate, args.directory)
    elif args.operation == "targets":
        data = targets(args.directory)
    else:
        data = completed(args.directory, args.report)
    save(args.report, data)
    if args.operation == "targets":
        print("\n".join(row["target"] for row in data["objects"]))
    else:
        print(json.dumps(data, indent=2))
    require(data["status"] == "PASS", "resource preflight failed; see saved checks and capacities")


if __name__ == "__main__":
    main()
