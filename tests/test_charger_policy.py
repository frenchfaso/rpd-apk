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
static int refs, writes, usb, fault=-1, guard_error, queued, read_error;
static unsigned char bus[4][2];
static int read_setting(unsigned int i, unsigned char *v) {
    if (read_error) return -EIO;
    v[0]=bus[i][0]; v[1]=bus[i][1]; return 0;
}
static int write_setting(unsigned int i, const unsigned char *v) {
    writes++; bus[i][0]=v[0];
    if ((int)i==fault) return -EIO;
    bus[i][1]=v[1]; return 0;
}
#define CALLBACKS(name, index) \
static int name##_read(unsigned char *v) { return read_setting(index,v); } \
static int name##_write(const unsigned char *v) { return write_setting(index,v); }
CALLBACKS(threshold,0)
CALLBACKS(warm,1)
CALLBACKS(cold,2)
CALLBACKS(cold_stop,3)
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
        harness += source[source.index('/* -170 *'):source.index('static bool dirty(void)')]
        harness += function(source, 'static bool dirty(void)')
        harness += function(source, 'static void release_reference(void)')
        harness += function(source, 'static void restore_locked(void)')
        harness += function(source, 'static void update_locked(void)')
        harness += r'''
static void reset(void) {
    assert(refs==0);
    enabled=applied=pinned=false; result=restore_result=0;
    writes=usb=guard_error=queued=read_error=wake=0; fault=-1;
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        struct charger_transaction *t=settings[i];
        t->dirty=t->verified=0;
        bus[i][0]=t->baseline[0]; bus[i][1]=t->baseline[1];
    }
}
static void assert_original(void) {
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        assert(bus[i][0]==settings[i]->baseline[0]);
        assert(bus[i][1]==settings[i]->baseline[1]);
    }
}
static void apply(void) {
    enabled=true; usb=1; update_locked();
    assert(applied && refs==1 && !wake && writes==4);
}
int main(void) {
    assert(transaction.target[0]==0xfb && transaction.target[1]==0xa6);
    assert(warm_transaction.target[0]==0x0f && warm_transaction.target[1]==0xb3);
    assert(cold_transaction.target[0]==0x25 && cold_transaction.target[1]==0x7d);
    assert(cold_stop_transaction.target[0]==0x37 && cold_stop_transaction.target[1]==0x33);
    reset(); update_locked(); assert(writes==0);
    enabled=true; update_locked(); assert(writes==0 && result==-EAGAIN);
    usb=1; guard_error=-ERANGE; update_locked();
    assert(writes==0 && enabled && result==-ERANGE);
    guard_error=0; update_locked(); assert(writes==4 && applied && refs==1 && !wake);
    update_locked(); assert(writes==4 && refs==1);
    enabled=false; restore_locked(); assert(!dirty() && refs==0 && !wake); assert_original();
    /* Any one register may reset while the other three remain owned. */
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        reset(); apply(); usb=0;
        bus[i][0]=settings[i]->baseline[0]; bus[i][1]=settings[i]->baseline[1];
        update_locked(); assert(writes==4 && !applied && refs==1 && enabled);
        usb=1; update_locked(); assert(writes==5 && applied && refs==1 && !wake);
        enabled=false; restore_locked(); assert(!dirty() && refs==0 && !wake); assert_original();
    }
    /* Complete power-cycle reset drops ownership without extra writes. */
    reset(); apply(); usb=0;
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        bus[i][0]=settings[i]->baseline[0]; bus[i][1]=settings[i]->baseline[1];
    }
    update_locked(); assert(writes==4 && refs==0 && !dirty() && !applied);
    reset(); enabled=true; usb=1;
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        bus[i][0]=settings[i]->target[0]; bus[i][1]=settings[i]->target[1];
    }
    update_locked(); assert(applied && refs==0 && !dirty() && writes==0);
    /* Fault at any write rolls back every previously owned setting. */
    for (int i=0;i<4;i++) {
        reset(); enabled=true; usb=1; fault=i; update_locked();
        assert(!enabled && dirty() && refs==1 && wake && queued==1);
        int n=writes; update_locked(); assert(writes==n);
        fault=-1; restore_locked(); assert(!dirty() && refs==0 && !wake); assert_original();
    }
    /* Unknown values are refused before applying, or preserved on teardown. */
    for (unsigned int i=0;i<ARRAY_SIZE(settings);i++) {
        reset(); enabled=true; usb=1; bus[i][1]^=1; update_locked();
        assert(!enabled && result==-ESTALE && !dirty() && writes==0 && refs==0);
        reset(); apply(); bus[i][1]^=1; unsigned char foreign=bus[i][1];
        update_locked(); assert(!enabled && result==-ESTALE && !dirty() && refs==0);
        assert(writes==7 && bus[i][1]==foreign);
    }
    reset(); apply(); read_error=1; update_locked();
    assert(result==-EIO && refs==1 && dirty() && writes==4);
    read_error=0; update_locked(); assert(applied && result==0);
    enabled=false; restore_locked(); assert(!dirty() && refs==0 && !wake); assert_original();
    puts("PASS: actual four-setting policy and OEM bytes, independent reset, ownership, partial-write rollback and retry");
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
