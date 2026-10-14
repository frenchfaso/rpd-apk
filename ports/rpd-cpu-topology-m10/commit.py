#!/usr/bin/env python3
"""Recompose M10 boot files after APK has saved the installed package database."""
from pathlib import Path
import shutil
import subprocess
import sys


def finish(stage, root=Path('/'), run=subprocess.run, find=shutil.which):
    pending = root / 'run/rpd-m10-boot.pending'
    if stage != 'post-commit' or not pending.exists():
        return
    if not (root / 'usr/share/deviceinfo/deviceinfo').exists():
        return
    mkinitfs = find('mkinitfs')
    if not mkinitfs:
        return
    print('rpd-cpu-topology-m10: recomposing boot files with committed APK versions', flush=True)
    run([mkinitfs], check=True)
    # boot-deploy queues this again during mkinitfs. Clear it only on success.
    pending.unlink(missing_ok=True)


if __name__ == '__main__':
    finish(sys.argv[1] if len(sys.argv) > 1 else '')
