"""Compile the actual kernel policy functions against a fault-injected bus."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


def function(source, signature):
    start = source.index(signature)
    body = source.index('{', start)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class ChargerPolicyTests(unittest.TestCase):
    def test_real_update_policy(self):
        port = Path(__file__).parents[1] / 'ports/rpd-backlight-m10'
        source = (port / 'm10_charger.c').read_text()
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include "m10_charger_transaction.h"
#define BIT(n) (1u << (n))
#define THIS_MODULE 0
#define HZ 1
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static bool enabled, pinned, applied;
static int result, restore_result, wake, map, system_wq, rollback_work;
static int refs, writes, usb, fault, guard_error, queued;
static unsigned char bus[2] = {0x7b, 0xa4};
static int threshold_read(unsigned char *v) { v[0]=bus[0]; v[1]=bus[1]; return 0; }
static int threshold_write(const unsigned char *v) {
    writes++;
    if (fault) return -EIO;
    bus[0]=v[0]; bus[1]=v[1]; return 0;
}
static struct term_transaction transaction = {.read=threshold_read,.write=threshold_write};
static int regmap_read(int m, unsigned int address, unsigned int *v) {
    (void)m; assert(address==0x1310); *v=usb ? BIT(4) : 0; return 0;
}
static int guards(void) { return guard_error; }
static int try_module_get(int m) { (void)m; refs++; return 1; }
static void module_put(int m) { (void)m; assert(refs>0); refs--; }
static void __pm_stay_awake(int w) { (void)w; wake=1; }
static void __pm_relax(int w) { (void)w; wake=0; }
static void mod_delayed_work(int w, int *job, int delay) {
    (void)w; (void)job; assert(delay==5); queued++;
}
'''
        harness += function(source, 'static void restore_locked(void)')
        harness += function(source, 'static void update_locked(void)')
        harness += r'''
int main(void) {
    update_locked(); assert(writes==0); /* Disabled means no configuration. */
    enabled=true;
    update_locked(); assert(writes==0 && enabled && result==-EAGAIN);
    usb=1; guard_error=-ERANGE;
    update_locked(); assert(writes==0 && enabled && result==-ERANGE);
    guard_error=0;
    update_locked(); assert(writes==1 && applied && refs==1 && wake==0);
    update_locked(); assert(writes==1 && refs==1); /* Repeated events are read-only. */
    usb=0;
    update_locked(); assert(writes==1 && applied && refs==1); /* Retained configuration. */
    bus[0]=0x7b; bus[1]=0xa4; /* Simulate hardware defaults after power loss. */
    update_locked(); assert(writes==1 && !applied && refs==0 && enabled);
    usb=1;
    update_locked(); assert(writes==2 && applied && refs==1 && !wake);
    enabled=false; restore_locked();
    assert(!transaction.dirty && refs==0 && !wake && bus[0]==0x7b && bus[1]==0xa4);
    bus[0]=0xfb; bus[1]=0xa6; enabled=true;
    update_locked(); assert(applied && refs==0 && !transaction.dirty);
    int previous_writes=writes;
    update_locked(); assert(writes==previous_writes && refs==0);
    bus[1]=0xa7; /* Future/native driver's different value. */
    update_locked(); assert(!enabled && result==-ESTALE && writes==previous_writes);
    bus[0]=0x7b; bus[1]=0xa4; enabled=true; fault=1;
    update_locked(); assert(!enabled && transaction.dirty && refs==1 && wake && queued==1);
    update_locked(); assert(refs==1 && wake); /* No application retries after write fault. */
    fault=0; restore_locked(); assert(!transaction.dirty && refs==0 && !wake);
    puts("PASS: real charger policy, deferred USB, guard wait, reconnect/reset, ownership and write-fault rollback");
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            c = Path(temp) / 'policy.c'
            exe = Path(temp) / 'policy'
            c.write_text(harness)
            subprocess.run([shutil.which('cc') or 'clang', '-std=c11', '-Wall', '-Wextra',
                            '-Werror', '-I', str(port), str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
