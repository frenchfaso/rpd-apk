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
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u << (n))
#define THIS_MODULE 0
#define HZ 1
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static bool enabled, pinned, applied;
static int result, restore_result, wake, map, system_wq, rollback_work;
static int refs, writes, usb, fault, guard_error, queued, fail_warm, read_error;
static unsigned char bus[2] = {0x7b, 0xa4}, warm[2] = {0x1b, 0xff};
static int threshold_read(unsigned char *v) { if (read_error) return -EIO; v[0]=bus[0]; v[1]=bus[1]; return 0; }
static int threshold_write(const unsigned char *v) {
    writes++;
    if (fault) return -EIO;
    bus[0]=v[0]; bus[1]=v[1]; return 0;
}
static int warm_read(unsigned char *v) { v[0]=warm[0]; v[1]=warm[1]; return 0; }
static int warm_write(const unsigned char *v) {
    writes++;
    warm[0]=v[0];
    if (fail_warm) return -EIO; /* partial write */
    warm[1]=v[1]; return 0;
}
static struct charger_transaction transaction = {
 .read=threshold_read,.write=threshold_write,.baseline={0x7b,0xa4},.target={0xfb,0xa6}};
static struct charger_transaction warm_transaction = {
 .read=warm_read,.write=warm_write,.baseline={0x1b,0xff},.target={0x0f,0xb3}};
static struct charger_transaction *settings[] = {&transaction,&warm_transaction};
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
        harness += function(source, 'static bool dirty(void)')
        harness += function(source, 'static void release_reference(void)')
        harness += function(source, 'static void restore_locked(void)')
        harness += function(source, 'static void update_locked(void)')
        harness += r'''
int main(void) {
    update_locked(); assert(writes==0);
    enabled=true;
    update_locked(); assert(writes==0 && enabled && result==-EAGAIN);
    usb=1; guard_error=-ERANGE;
    update_locked(); assert(writes==0 && enabled && result==-ERANGE);
    guard_error=0;
    update_locked(); assert(writes==2 && applied && refs==1 && wake==0);
    assert(transaction.dirty && warm_transaction.dirty);
    update_locked(); assert(writes==2 && refs==1);
    usb=0;
    update_locked(); assert(writes==2 && applied && refs==1);
    bus[0]=0x7b; bus[1]=0xa4; /* One setting resets, the other stays owned. */
    update_locked(); assert(writes==2 && !applied && refs==1 && enabled);
    assert(!transaction.dirty && warm_transaction.dirty);
    usb=1;
    update_locked(); assert(writes==3 && applied && refs==1 && !wake);
    enabled=false; restore_locked();
    assert(!dirty() && refs==0 && !wake && bus[0]==0x7b && warm[0]==0x1b);
    bus[0]=0xfb; bus[1]=0xa6; warm[0]=0x0f; warm[1]=0xb3; enabled=true;
    update_locked(); assert(applied && refs==0 && !dirty());
    int previous_writes=writes;
    update_locked(); assert(writes==previous_writes && refs==0);
    warm[1]=0xb4; /* Future/native driver's different value. */
    update_locked(); assert(!enabled && result==-ESTALE && writes==previous_writes);
    assert(warm[1]==0xb4);
    bus[0]=0x7b; bus[1]=0xa4; warm[0]=0x1b; warm[1]=0xff;
    enabled=true; fault=1;
    update_locked(); assert(!enabled && dirty() && refs==1 && wake && queued==1);
    update_locked(); assert(refs==1 && wake);
    fault=0; restore_locked(); assert(!dirty() && refs==0 && !wake);
    /* Second-setting partial failure must roll back the first too. */
    enabled=true; fail_warm=1;
    update_locked(); assert(!enabled && warm_transaction.dirty && !transaction.dirty);
    assert(bus[0]==0x7b && bus[1]==0xa4 && refs==1 && wake);
    fail_warm=0; restore_locked();
    assert(!dirty() && refs==0 && !wake && warm[0]==0x1b && warm[1]==0xff);
    /* Unknown warm value must be rejected before touching termination. */
    enabled=true; warm[1]=0xfe; previous_writes=writes;
    update_locked(); assert(result==-ESTALE && writes==previous_writes && !enabled);
    warm[1]=0xff; enabled=true; update_locked(); assert(applied && refs==1);
    /* A new warm owner causes restoration only of our termination value. */
    warm[1]=0xb4; previous_writes=writes;
    update_locked(); assert(!enabled && result==-ESTALE && !dirty() && refs==0);
    assert(writes==previous_writes+1 && bus[0]==0x7b && warm[1]==0xb4);
    /* Read failures preserve owned snapshots and permit a later clean read. */
    warm[0]=0x1b; warm[1]=0xff; enabled=true; update_locked();
    read_error=1; previous_writes=writes; update_locked();
    assert(result==-EIO && refs==1 && dirty() && writes==previous_writes);
    read_error=0; update_locked(); assert(applied && result==0);
    enabled=false; restore_locked(); assert(!dirty() && refs==0 && !wake);
    puts("PASS: two-setting policy, USB deferral, independent reset, ownership, partial-write rollback and retry");
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
