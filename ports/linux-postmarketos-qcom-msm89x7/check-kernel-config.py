#!/usr/bin/env python3
"""Keep the official kernel config while allowing equivalent host-tool metadata."""
import difflib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def pahole_version(text):
    values = re.findall(r'^CONFIG_PAHOLE_VERSION=([0-9]+)$', text, re.M)
    if len(values) != 1:
        raise ValueError('Expected one numeric CONFIG_PAHOLE_VERSION')
    return int(values[0])


def normalized(text):
    return ''.join(line for line in text.splitlines(keepends=True)
                   if line.rstrip('\n') != 'CONFIG_CC_CAN_LINK=y'
                   and not re.fullmatch(r'CONFIG_PAHOLE_VERSION=[0-9]+\n?', line))


def btf_flags(config, kernel, external=False):
    # Evaluate the current kernel's own BTF rules with each configuration.
    # Use its own Kbuild predicates too; no feature thresholds or pahole versions
    # are duplicated here.
    rules = """.PHONY: rpd-btf-flags
rpd-btf-flags:
\t@printf '%s\\n' '$(PAHOLE_FLAGS)'
\t@printf '%s\\n' '$(RESOLVE_BTFIDS_FLAGS)'
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.mk') as helper:
        helper.write(rules)
        helper.flush()
        env = os.environ.copy()
        env.pop('MAKEFLAGS', None)
        env.pop('MFLAGS', None)
        env.pop('GNUMAKEFLAGS', None)
        output = subprocess.check_output([
            'make', '-s', '--no-print-directory', '-C', str(kernel),
            '-f', 'scripts/Kbuild.include', '-f', str(config.resolve()),
            '-f', helper.name,
            '-f', 'scripts/Makefile.btf', 'rpd-btf-flags',
            'KBUILD_EXTMOD=' + ('1' if external else ''),
        ], env=env, text=True)
        return tuple(tuple(line.split()) for line in output.splitlines())


def check(expected, actual, kernel):
    before, after = expected.read_text(), actual.read_text()
    old, new = pahole_version(before), pahole_version(after)
    a, b = normalized(before), normalized(after)
    if a != b:
        delta = ''.join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                           fromfile=str(expected), tofile=str(actual)))
        raise ValueError('Kernel configuration changed:\n' + delta)
    if old != new and 'CONFIG_DEBUG_INFO_BTF=y' in before.splitlines():
        for external in [False, True]:
            if btf_flags(expected, kernel, external) != btf_flags(actual, kernel, external):
                raise ValueError('pahole version changes the kernel BTF flags')
    print(f'Kernel configuration matches; pahole metadata {old} -> {new}')


if __name__ == '__main__':
    try:
        check(*(Path(arg) for arg in sys.argv[1:]))
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
