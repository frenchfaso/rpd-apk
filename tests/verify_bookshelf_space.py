#!/usr/bin/env python3
"""Compile and exercise the actual patched free_space() against statvfs fixtures."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
function = re.search(r'static curl_off_t free_space \(void\)\n\{.*?\n\}', source, re.S).group()
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/statvfs.h>
#define G_MAXINT64 INT64_MAX
typedef int64_t curl_off_t;
static FILE *outfile;
static struct statvfs fixture;
static int fail;
static int probe(int fd, struct statvfs *result) {
    assert(fd == fileno(outfile));
    if (fail) return -1;
    *result = fixture;
    return 0;
}
#define fstatvfs probe
''' + function + r'''
#undef fstatvfs
int main(void) {
    assert(free_space() == 0); /* no open download */
    outfile = tmpfile();
    assert(outfile);
    fixture.f_frsize = 4096;
    fixture.f_bfree = 999;
    fixture.f_bavail = 10;
    assert(free_space() == 40960); /* user-available, not root-reserved */
    fixture.f_bavail = 1000000;
    assert(free_space() == INT64_C(4096000000)); /* > 32-bit signed range */
    fixture.f_bavail = 0;
    assert(free_space() == 0);
    fixture.f_bavail = (fsblkcnt_t)-1;
    assert(free_space() == INT64_MAX); /* saturate, never wrap */
    fixture.f_frsize = 0;
    assert(free_space() == 0);
    fixture.f_frsize = 4096;
    fail = 1;
    assert(free_space() == 0);
    fclose(outfile);
    puts("Bookshelf statvfs destination, available-space and overflow checks passed");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'probe.c').write_text(program)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    subprocess.run([str(path / 'probe')], check=True)
