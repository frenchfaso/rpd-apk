from pathlib import Path
import subprocess,tempfile,sys
p=Path(__file__).resolve().parent
s=Path(sys.argv[1]).read_text();a=s.index('static int set_panel_sleep(');b=s.index('/* Retained timing stop',a);c=s.index('/* Fall back to panel-only sleep');e=s.index('static int update_status(',c)
f=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint8_t u8;
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define PM_SUSPEND_PREPARE 1
#define PM_POST_SUSPEND 2
#define NOTIFY_OK 0
#define dev_err(...) ((void)0)
'''+s[s.index('struct panel_cmd {'):s.index('#define BASE')]+r'''
struct notifier_block { int (*notifier_call)(struct notifier_block *,unsigned long,void *); };
static bool panel_asleep,retention_active,scanout_available;
static int timing_pause(void) { assert(0); return -5; }
static int timing_run(void) { return 0; }
static unsigned int panel_sleeps,panel_wakes;
static void *bl;
static int lock,calls,fail_at,waited,last_cmd,last_val;
static int send_short(u8 type,u8 cmd,u8 value) {
 assert(type==5 || type==21);calls++;last_cmd=cmd;last_val=value;
 return calls==fail_at ? -5 : 0;
}
static void msleep(int ms) { waited+=ms; }
static int backlight_get_brightness(void *unused) { return 26; }
static int notifier_from_errno(int err) { return err; }
static void mutex_lock(void *unused) {}
static void mutex_unlock(void *unused) {}
'''+s[a:b]+s[c:e]+r'''
int main(void) {
 assert(!panel_pm_nb.notifier_call(0,PM_SUSPEND_PREPARE,0) && !calls);
 retention_active=true;
 assert(!panel_pm_nb.notifier_call(0,99,0) && !calls);
 assert(!panel_pm_nb.notifier_call(0,PM_SUSPEND_PREPARE,0));
 assert(panel_asleep && panel_sleeps==1 && !panel_wakes && calls==5 && waited==140);
 calls=waited=0;
 assert(!panel_pm_nb.notifier_call(0,PM_POST_SUSPEND,0));
 assert(!panel_asleep && panel_wakes==1 && calls==17 && waited==130);
 assert(last_cmd==0x51 && last_val==26);
 calls=0;fail_at=1;
 assert(panel_pm_nb.notifier_call(0,PM_SUSPEND_PREPARE,0)==-5);
 assert(calls==1 && panel_sleeps==1);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 t=Path(d);(t/'test.c').write_text(f)
 subprocess.run(['cc','-Wall','-Wextra','-Wno-unused-parameter','-Wno-unused-variable',*(['-fsanitize=address,undefined'] if '--sanitize' in sys.argv[2:] else []),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
print('PASS: automatic suspend/resume, retention guard, unrelated events, transport error propagated')
