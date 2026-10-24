#!/usr/bin/env python3
"""Fail before signing when the complete public site cannot fit GitHub Pages."""
import argparse
import json
from pathlib import Path

# Conservative decimal 1GB bound; retain space for signatures and final receipts.
LIMIT = 1_000_000_000
RESERVE = 1024 * 1024


def measure(output, extras=(), limit=LIMIT):
    files = []
    for root in [output, *extras]:
        if not root.exists() or root.is_symlink():
            raise ValueError('Missing regular public archive input: ' + str(root))
        paths = root.rglob('*') if root.is_dir() else [root]
        for path in paths:
            if path.is_symlink():
                raise ValueError('Public archive contains a symlink: ' + str(path))
            if path.is_file():
                files.append({'path': str(path), 'bytes': path.stat().st_size})
    total = sum(item['bytes'] for item in files)
    return {'status': 'PAGES_SIZE_OK' if total + RESERVE <= limit else 'PAGES_SIZE_EXCEEDED',
            'bytes': total, 'reserved_bytes': RESERVE, 'limit_bytes': limit,
            'largest_files': sorted(files, key=lambda item: item['bytes'], reverse=True)[:15]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--extra', action='append', type=Path, default=[])
    args = parser.parse_args()
    result = measure(args.output, args.extra)
    (args.output/'pages-size.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if result['status'] != 'PAGES_SIZE_OK':
        raise SystemExit('Public site exceeds the Pages size bound; retain sources/debug data and review distribution before signing')


if __name__ == '__main__':
    main()
