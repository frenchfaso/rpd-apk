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
import struct
import subprocess

APORTS = "a44854115ef1a1cda0c41b3e6f0974f51755d736"
BASE_RECIPE = "11eaf1455db582568e715bb161e4b890618977accf65ac3d89f6f4373bed8252"
# Pinned Chromium BUILDCONFIG resolves empty Linux CPU/OS to native host values.
BUILD_CONFIG = "4d6c39685c8c8ae6529211a9c770890015c858bad35d8b8ce4f3437ecdbcb66f"
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


def checksum_order(recipe):
    """Check the pinned recipe's positional abuild source/checksum contract."""
    variables = dict(re.findall(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z0-9_.-]+)$", recipe))
    source = re.search(r'(?ms)^source="(.*?)"\n', recipe)
    sums = re.search(r'(?ms)^sha512sums="(.*?)"\n', recipe)
    require(source is not None and sums is not None, "source or checksum block missing")
    expanded = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)",
                      lambda match: variables[match[1]], source[1])
    names = [token.split("::", 1)[0] if "::" in token else token.rsplit("/", 1)[-1]
             for token in expanded.split()]
    words = sums[1].split()
    require(len(words) == 2 * len(names), "source/checksum count differs")
    entries = list(zip(words[::2], words[1::2]))
    require(all(re.fullmatch(r"[0-9a-f]{128}", value) for value, _ in entries),
            "malformed SHA512 value")
    require([name for _, name in entries] == names, "source/checksum positional order differs")
    return entries


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
    original = checksum_order((candidate / "upstream/aports/community/chromium/APKBUILD").read_text())
    entries = checksum_order((candidate / "prepared/aports/community/chromium/APKBUILD").read_text())
    broker = candidate / "patches/chromium-linux-v4l2-decoder-broker.patch"
    require(entries[:-1] == original, "original source checksum values/order changed")
    require(entries[-1] == (hashlib.sha512(broker.read_bytes()).hexdigest(), broker.name),
            "broker checksum missing from final source position")
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
            "staged_recipe_sha256": sha(port / "APKBUILD"), "broker_sha256": sha(broker),
            "source_checksum_pairs": len(checksum_order((port / "APKBUILD").read_text())),
            "original_source_checksums": "Preserved in original positional order"}


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


def gn_value(text, name):
    matches = re.findall(r"^" + re.escape(name) + r"\s*=\s*(.*?)\s*$", text, re.M)
    require(len(matches) == 1, "missing or ambiguous GN argument: " + name + ": " + repr(text))
    return matches[0]


def native_cpu(cpu, target_os, system, machine, config_hash):
    require(system == "Linux" and machine == "aarch64", "GN host is not native Linux/aarch64")
    require(cpu in ('""', '"arm64"'), "GN target_cpu is not arm64/native: " + cpu)
    require(target_os in ('""', '"linux"'), "GN target_os is not Linux/native: " + target_os)
    if cpu == '""' or target_os == '""':
        require(config_hash == BUILD_CONFIG, "native GN defaults differ from exact pinned BUILDCONFIG")
    return "arm64"


def arm64_object(path):
    with path.open("rb") as stream:
        header = stream.read(20)
    require(len(header) == 20 and header[:4] == b"\x7fELF" and header[4:6] == b"\x02\x01",
            "object is not little-endian ELF64: " + str(path))
    machine = struct.unpack_from("<H", header, 18)[0]
    require(machine == 183, "object is not AARCH64 (ELF machine " + str(machine) + "): " + str(path))
    return "AARCH64"


def targets(source, diagnostic=None):
    output = source / "out/bld"
    reported = {name: None for name in ("target_cpu", "target_os", "use_v4l2_codec", "use_vaapi")}
    evidence = {"status": "UNPROVEN", "raw_gn_arguments": reported,
                "runtime_system": platform.system(), "runtime_machine": platform.machine(),
                "buildconfig_sha256": sha(source / "build/config/BUILDCONFIG.gn"),
                "gn_version": None}
    if diagnostic is not None:
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "build/config/BUILDCONFIG.gn",
                        diagnostic.with_name("gn-effective-buildconfig.gn"))
        save(diagnostic, evidence)
    try:
        evidence["gn_version"] = run(["gn", "--version"], source).strip()
    except subprocess.CalledProcessError as exc:
        evidence.update(status="FAIL", query_failed="version", query_output=exc.output,
                        exit_code=exc.returncode)
        if diagnostic is not None:
            save(diagnostic, evidence)
        raise
    for name in ("target_cpu", "target_os", "use_v4l2_codec", "use_vaapi"):
        try:
            reported[name] = run(["gn", "args", str(output), "--list=" + name, "--short"], source)
        except subprocess.CalledProcessError as exc:
            reported[name] = exc.output
            evidence.update(status="FAIL", query_failed=name, exit_code=exc.returncode)
            if diagnostic is not None:
                save(diagnostic, evidence)
            raise
        if diagnostic is not None:
            save(diagnostic, evidence)
    flags = {}
    flags["target_cpu"] = native_cpu(gn_value(reported["target_cpu"], "target_cpu"),
                                     gn_value(reported["target_os"], "target_os"),
                                     evidence["runtime_system"], evidence["runtime_machine"],
                                     evidence["buildconfig_sha256"])
    for name in ("use_v4l2_codec", "use_vaapi"):
        expected = "true"
        require(gn_value(reported[name], name) == expected,
                "wrong generated GN argument: " + name + ": " + repr(reported[name]))
        flags[name] = expected
    evidence.update(status="PASS", effective_target_cpu=flags["target_cpu"],
                    basis="Explicit arm64 or exact pinned native-default contract; compiled ELF machine still required")
    if diagnostic is not None:
        save(diagnostic, evidence)
    text = run(["ninja", "-C", str(output), "-t", "targets", "all"])
    selected = select_targets(text, source,
                              lambda target: run(["ninja", "-C", str(output), "-t", "query", target]))
    return {"status": "PASS", "gn_arguments": flags, "gn_target_evidence": evidence, "objects": selected}


def completed(source, report):
    data = json.loads(report.read_text())
    for row in data["objects"]:
        path = source / "out/bld" / row["target"]
        require(path.is_file() and path.stat().st_size > 0, "compiled object missing: " + row["target"])
        row.update(bytes=path.stat().st_size, sha256=sha(path), elf_machine=arm64_object(path))
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
        data = {"status": "PASS", "scope": "Retained candidate inputs and ordered source checksums"}
    elif args.operation == "stage":
        data = stage(args.candidate, args.directory)
    elif args.operation == "prepared":
        data = prepared(args.candidate, args.directory)
    elif args.operation == "targets":
        data = targets(args.directory, args.report.with_name("gn-arguments.json"))
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
