#!/usr/bin/env python3
"""Compile the patched upstream sysfs reader against fake battery fixtures.

Usage: python3 tests/verify_battery_sysfs.py /path/to/patched/pplug-batt
Requires a C compiler, pkg-config and glib development files.
"""
import pathlib
import shlex
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]) / 'src'
with tempfile.TemporaryDirectory(prefix='rpd-battery-test-') as directory:
    root = pathlib.Path(directory)
    supply = root / 'sysfs'
    (supply / 'BAT0').mkdir(parents=True)
    (root / 'batt_sys.c').write_bytes((source / 'batt_sys.c').read_bytes())
    (root / 'batt_sys.h').write_text((source / 'batt_sys.h').read_text().replace('/sys/class/power_supply', str(supply)))
    (root / 'test.c').write_text(r'''
#include "batt_sys.h"
#include <glib/gstdio.h>
#include <assert.h>
static void put(const char *name, const char *value) {
    gchar *path = g_build_filename(ACPI_PATH_SYS_POWER_SUPPLY, "BAT0", name, NULL);
    if (value) assert(g_file_set_contents(path, value, -1, NULL));
    else g_remove(path);
    g_free(path);
}
int main(void) {
    put("type", "Battery"); put("status", "Charging");
    put("current_now", "500000"); put("voltage_now", "4180000");
    battery *b = battery_get(0); assert(b);
    assert(b->percentage == -1); assert(b->seconds == -1);
    put("status", "Discharging"); put("current_now", "-317000");
    battery_update(b); assert(b->percentage == -1); assert(b->seconds == -1);
    put("capacity", "63"); battery_update(b); assert(b->percentage == 63);
    put("capacity", "0"); battery_update(b); assert(b->percentage == 0);
    put("capacity", "100"); battery_update(b); assert(b->percentage == 100);
    put("capacity", "invalid"); battery_update(b); assert(b->percentage == -1);
    put("capacity", "101"); battery_update(b); assert(b->percentage == -1);
    put("capacity", NULL); put("charge_now", "2425000"); put("charge_full", "4850000");
    battery_update(b); assert(b->percentage == 50); assert(b->seconds > 0);
    put("charge_full", "0"); battery_update(b); assert(b->percentage == -1);
    put("charge_full", NULL); put("charge_now", NULL);
    put("energy_now", "10000000"); put("energy_full", "20000000");
    battery_update(b); assert(b->percentage == 50);
    battery_free(b); return 0;
}
''')
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True))
    subprocess.run(['cc', '-Wall', str(root/'batt_sys.c'), str(root/'test.c'), '-o', str(root/'test'), *flags], check=True)
    subprocess.run([str(root/'test')], check=True)
print('PASS: missing capacity, charge/discharge, raw percentage, invalid data, zero denominator, charge/energy fallback')
