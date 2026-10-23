#!/usr/bin/env python3
"""Exercise the actual upstream cookie reader without running a setuid helper."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--sanitize', action='store_true')
    args = parser.parse_args()
    source = args.source.read_text()
    start = source.index('char *\nread_cookie (int argc, char **argv)\n{')
    end = source.index('\ngboolean\nsend_dbus_message', start)
    function = source[start:end]
    harness = '''#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <glib.h>
'''+function+'''
int main(int argc, char **argv)
{
    char *cookie = read_cookie(argc, argv);
    if (cookie == NULL) {
        printf("REJECT:%d\\n", errno);
    } else {
        printf("ACCEPT:%s\\n", cookie);
        free(cookie);
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='polkit-cookie-') as temporary:
        root = Path(temporary)
        (root/'cookie.c').write_text(harness)
        flags = shlex.split(subprocess.check_output(
            ['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True))
        command = shlex.split(os.environ.get('CC', 'cc'))
        command += ['-O2', '-Wall', '-Wextra', '-Werror']
        if args.sanitize:
            command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
        subprocess.run(command + [str(root/'cookie.c'), '-o', str(root/'cookie')] + flags,
                       check=True)
        cases = [
            (b'cookie\n', b'ACCEPT:cookie\n'),
            (b'cookie\r\n', b'ACCEPT:cookie\n'),
            (b'\n', b'ACCEPT:\n'),
            (b'x'*4096+b'\n', b'ACCEPT:'+b'x'*4096+b'\n'),
            (b'x'*4097+b'\n', b'REJECT:'),
            (b'x'*65536+b'\n', b'REJECT:'),
            (b'\0\n', b'REJECT:'),
            (b'cookie\0hidden\n', b'REJECT:'),
            (b'unterminated', b'REJECT:'),
            (b'', b'REJECT:'),
        ]
        for value, expected in cases:
            result = subprocess.run([str(root/'cookie')], input=value,
                                    capture_output=True, timeout=5, check=True)
            if expected == b'REJECT:':
                assert result.stdout.startswith(expected), (value[:20], result.stdout)
            else:
                assert result.stdout == expected, (value[:20], result.stdout)
        # Overlong input must be rejected even when the writer keeps its pipe
        # open. The superseded draining loop would wait indefinitely here.
        process = subprocess.Popen([str(root/'cookie')], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            process.stdin.write(b'x'*5000)
            process.stdin.flush()
            process.wait(timeout=5)
            assert process.returncode == 0
            assert process.stdout.read().startswith(b'REJECT:')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
        result = subprocess.check_output([str(root/'cookie'), 'user', 'legacy-cookie'])
        assert result == b'ACCEPT:legacy-cookie\n'
    print('Cookie parser: 12 boundary, compatibility and nonblocking checks passed')


if __name__ == '__main__':
    main()
