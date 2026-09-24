#!/usr/bin/env python3
"""Compile the actual M10 charger-state helper against near-full fixtures."""
import pathlib
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).read_text()
a = source.index('static int m10_charge_status(')
b = source.index('static int battery_get', a)
fixture = '''
#include <assert.h>
#include <stdbool.h>
enum { POWER_SUPPLY_STATUS_UNKNOWN, POWER_SUPPLY_STATUS_CHARGING,
       POWER_SUPPLY_STATUS_DISCHARGING, POWER_SUPPLY_STATUS_NOT_CHARGING,
       POWER_SUPPLY_STATUS_FULL };
'''
fixture += source[a:b]
fixture += '''
int main(void) {
 /* Observed after overnight suspend: taper, enabled, +11 mA. */
 assert(m10_charge_status(11000, 4, true, 0x99) == POWER_SUPPLY_STATUS_CHARGING);
 for (unsigned int state = 1; state <= 4; state++) {
  assert(m10_charge_status(0, state, true, 1) == POWER_SUPPLY_STATUS_CHARGING);
  assert(m10_charge_status(0, state, true, 0) == POWER_SUPPLY_STATUS_NOT_CHARGING);
 }
 assert(m10_charge_status(11000, 5, true, 0) == POWER_SUPPLY_STATUS_FULL);
 assert(m10_charge_status(11000, 0, true, 0) == POWER_SUPPLY_STATUS_NOT_CHARGING);
 assert(m10_charge_status(11000, 6, true, 0) == POWER_SUPPLY_STATUS_NOT_CHARGING);
 assert(m10_charge_status(11000, 7, true, 0) == POWER_SUPPLY_STATUS_NOT_CHARGING);
 assert(m10_charge_status(-30000, 4, true, 1) == POWER_SUPPLY_STATUS_DISCHARGING);
 assert(m10_charge_status(-30000, 5, true, 0) == POWER_SUPPLY_STATUS_DISCHARGING);
 assert(m10_charge_status(11000, 5, false, 0) != POWER_SUPPLY_STATUS_FULL);
 assert(m10_charge_status(200000, 5, true, 0) != POWER_SUPPLY_STATUS_FULL);
 assert(m10_charge_status(0, 4, false, 1) == POWER_SUPPLY_STATUS_UNKNOWN);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    (root / 'test.c').write_text(fixture)
    flags = ['-fsanitize=address,undefined'] if '--sanitize' in sys.argv[2:] else []
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', *flags,
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
print('PASS: taper, enable bits, termination, inhibit/pause/disable and discharge')
