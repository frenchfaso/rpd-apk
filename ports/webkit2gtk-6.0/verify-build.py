#!/usr/bin/env python3
"""Check the effective native GTK4 build and its exported runtime version."""
import argparse
import ctypes
import json
from pathlib import Path
import re


ENABLED = (
    'ENABLE_BUBBLEWRAP_SANDBOX', 'ENABLE_JIT', 'ENABLE_WEBASSEMBLY',
    'ENABLE_WEBGL', 'ENABLE_GPU_PROCESS', 'ENABLE_VIDEO', 'ENABLE_WEB_AUDIO',
    'ENABLE_MEDIA_SOURCE', 'ENABLE_WAYLAND_TARGET', 'ENABLE_X11_TARGET',
    'USE_GTK4', 'USE_GBM', 'USE_LIBDRM', 'USE_GSTREAMER', 'USE_GSTREAMER_GL',
    'USE_SKIA', 'USE_ANGLE',
)
DISABLED = ('USE_GSTREAMER_FULL', 'USE_VULKAN')
LIBRARIES = {
    'webkit': 'libwebkitgtk-6.0.so.4',
    'jsc': 'libjavascriptcoregtk-6.0.so.1',
}


def configuration(builddir, version):
    header = (builddir / 'cmakeconfig.h').read_text()
    definitions = dict(re.findall(r'^#define ([A-Z][A-Z0-9_]*) (.+)$', header, re.M))
    for name, value in [(name, '1') for name in ENABLED] + [
            (name, '0') for name in DISABLED]:
        if definitions.get(name) != value:
            raise ValueError(f'{name}: expected {value}, got {definitions.get(name)!r}')
    if definitions.get('WEBKITGTK_API_VERSION') != '"6.0"':
        raise ValueError('the GTK4 WebKitGTK 6.0 API is required')
    ninja = (builddir / 'build.ninja').read_text()
    for name in ('ANGLE_ENABLE_OPENGL', 'USE_SYSTEM_EGL'):
        if not re.search(r'(?<!\S)-D' + name + r'(?:=1)?(?=\s)', ninja):
            raise ValueError(f'the native ANGLE OpenGL backend requires {name}')
    pc = (builddir / 'Source/WebKit/webkitgtk-6.0.pc').read_text()
    found = re.search(r'^Version:\s*(\S+)\s*$', pc, re.M)
    if not found or found[1] != version:
        raise ValueError(f'pkg-config version does not match {version}')
    return {'version': version, 'api': '6.0', 'angle_backend': 'system EGL/OpenGL',
            'features': {name: definitions[name] == '1' for name in ENABLED + DISABLED}}


def runtime(library_dir, version):
    versions = {}
    for prefix, soname in LIBRARIES.items():
        library = ctypes.CDLL(str(library_dir / soname))
        numbers = []
        for part in ('major', 'minor', 'micro'):
            function = getattr(library, f'{prefix}_get_{part}_version')
            function.argtypes = []
            function.restype = ctypes.c_uint
            numbers.append(function())
        actual = '.'.join(map(str, numbers))
        if actual != version:
            raise ValueError(f'{soname}: expected {version}, got {actual}')
        versions[soname] = actual
    return {'libraries': versions,
            'scope': 'Library loading and exported ABI version; no browser or hardware test.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    config = sub.add_parser('config')
    config.add_argument('builddir', type=Path)
    config.add_argument('--version', required=True)
    probe = sub.add_parser('runtime')
    probe.add_argument('--library-dir', type=Path, default=Path('/usr/lib'))
    probe.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        result = (configuration(args.builddir, args.version) if args.command == 'config'
                  else runtime(args.library_dir, args.version))
    except (ValueError, OSError, AttributeError) as error:
        parser.exit(1, f'WebKit candidate check failed: {error}\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
