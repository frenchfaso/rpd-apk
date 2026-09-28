from pathlib import Path
import subprocess,tempfile,sys
p=Path(__file__).resolve().parent;s=Path(sys.argv[1]).read_text()
a=s.index('static bool timing_stopped,');b=s.index('static void disable_scanout_sleep(',a)
c=s.index('static bool panel_pm_registered;');e=s.index('static int update_status(',c)
f=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
typedef uint32_t u32;
#define module_param(...)
#define PM_SUSPEND_PREPARE 1
#define PM_POST_SUSPEND 2
#define NOTIFY_OK 0
#define dev_err(...) ((void)0)
static bool retention_active=true;
static int lock;
static void mutex_lock(void *unused) {}
static void mutex_unlock(void *unused) {}
static int notifier_from_errno(int err) { return err; }
struct notifier_block { int (*notifier_call)(struct notifier_block *,unsigned long,void *); };
static u32 regs[64];
static unsigned char *intf_regs=(void *)regs;
static bool panel_asleep,fail_panel,keep_running,fail_restart;
static int writes;
static u32 readl(const void *p) { return *(const u32 *)p; }
static void writel(u32 v,void *p) { assert(panel_asleep); writes++;*(u32 *)p=v; }
static void msleep(int ms) { if ((regs[0] || keep_running) && !fail_restart) regs[0xac/4]++; }
static int set_panel_sleep(bool sleep) { if(fail_panel)return -EIO;panel_asleep=sleep;return 0; }
#define readl_poll_timeout(addr,value,cond,delay,timeout) ({ msleep(1); value=readl(addr); (cond)?0:-ETIMEDOUT; })
'''+s[a:b]+s[c:e]+r'''
static void reset(void) {
 regs[0]=1;regs[1]=0x80000000;regs[2]=0x042b0064;regs[3]=0x0015d96a;regs[0x90/4]=0x213f;
 timing_stops=timing_starts=0;scanout_available=retention_active=true;
 timing_stopped=panel_asleep=fail_panel=keep_running=fail_restart=false;writes=0;
}
int main(void) {
 reset(); assert(!timing_pause() && timing_stopped && panel_asleep && !regs[0] && writes==1);
 assert(!timing_pause() && writes==1);
 assert(!timing_run() && !timing_stopped && regs[0] && writes==2);
 assert(!set_panel_sleep(false) && !panel_asleep);
 reset();regs[2]++;assert(timing_pause()==-EIO && !writes && !panel_asleep);
 reset();fail_panel=true;assert(timing_pause()==-EIO && !writes);
 reset();keep_running=true;assert(timing_pause()==-EIO && !timing_stopped && !panel_asleep && regs[0]);
 reset();assert(!timing_pause());fail_restart=true;assert(timing_run()==-ETIMEDOUT && timing_stopped && panel_asleep);
 reset();assert(!panel_pm_notify(0,PM_SUSPEND_PREPARE,0));
 assert(timing_stops==1 && !timing_starts && timing_stopped && panel_asleep);
 assert(!panel_pm_notify(0,PM_POST_SUSPEND,0));
 assert(timing_starts==1 && !timing_stopped && !panel_asleep);
 reset();scanout_available=false;
 assert(!panel_pm_notify(0,PM_SUSPEND_PREPARE,0) && panel_asleep && !writes);
 assert(!panel_pm_notify(0,PM_POST_SUSPEND,0) && !panel_asleep && !writes);
 reset();retention_active=false;
 assert(!panel_pm_notify(0,PM_SUSPEND_PREPARE,0) && !panel_asleep && !writes);
 reset();assert(!panel_pm_notify(0,99,0) && !writes);
 reset();assert(!panel_pm_notify(0,PM_SUSPEND_PREPARE,0));fail_restart=true;
 assert(panel_pm_notify(0,PM_POST_SUSPEND,0)==-ETIMEDOUT && panel_asleep && timing_stopped);
 reset();regs[2]++;
 assert(panel_pm_notify(0,PM_SUSPEND_PREPARE,0)==-EIO && !writes);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 t=Path(d);(t/'test.c').write_text(f)
 subprocess.run(['cc','-Wall','-Wextra','-Wno-unused-parameter','-Wno-unused-variable',*(['-fsanitize=address,undefined'] if '--sanitize' in sys.argv[2:] else []),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
print('PASS: timing qualification, panel-first stop, idempotence, failed stop rollback, restart timeout, automatic PM order and fallback')
