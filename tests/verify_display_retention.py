#!/usr/bin/env python3
"""Compile actual retention helpers against failure-injection device fixtures."""
import pathlib,subprocess,sys,tempfile
source=pathlib.Path(sys.argv[1]).read_text()
a=source.index('static struct platform_device *firmware_fb;')
b=source.index('static void __iomem *regs;',a)
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#define module_param(...)
#define MODULE_PARM_DESC(...)
#define GENPD_NOTIFY_PRE_OFF 1
#define GENPD_NOTIFY_ON 2
#define NOTIFY_OK 1
struct notifier_block { int (*notifier_call)(struct notifier_block *, unsigned long, void *); };
struct generic_pm_domain { const char *name; };
struct driver { const char *name; };
struct device { struct driver *driver; struct generic_pm_domain *pm_domain; };
struct platform_device { struct device dev; };
struct device_node { int unused; };
static struct driver driver={"simple-framebuffer"};
static struct generic_pm_domain domain={"mdss_gdsc"};
static struct platform_device device={{&driver,&domain}};
static struct device_node node;
static bool node_present=true, device_present=true, domain_on=true;
static int add_error,adds,removes,puts,node_puts;
static struct device_node *of_find_compatible_node(void *a,void *b,const char *c){return node_present?&node:0;}
static struct platform_device *of_find_device_by_node(void *n){return device_present?&device:0;}
static void of_node_put(void *n){node_puts++;}
static void put_device(void *d){puts++;}
static bool dev_pm_genpd_is_on(void *d){return domain_on;}
static struct generic_pm_domain *pd_to_genpd(struct generic_pm_domain *p){return p;}
static int dev_pm_genpd_add_notifier(void *d,void *n){adds++;return add_error;}
static void dev_pm_genpd_remove_notifier(void *d){removes++;}
static int notifier_from_errno(int e){return e;}
'''+source[a:b]+r'''
static void reset(void){
 node_present=device_present=domain_on=true;driver.name="simple-framebuffer";
 domain.name="mdss_gdsc";device.dev.driver=&driver;
 adds=removes=puts=node_puts=add_error=0;retain_display=true;
 assert(!retention_active);assert(!firmware_fb);
}
int main(void){
 reset();retain_display=false;assert(enable_display_retention()==0);assert(!adds&&!puts);
 reset();node_present=false;assert(enable_display_retention()==-ENODEV);assert(!puts);
 reset();device_present=false;assert(enable_display_retention()==-ENODEV);assert(node_puts==1&&!puts);
 reset();device.dev.driver=0;assert(enable_display_retention()==-ENODEV);assert(puts==1&&!adds);
 reset();driver.name="native-dsi";assert(enable_display_retention()==-ENODEV);assert(puts==1&&!adds);
 reset();domain_on=false;assert(enable_display_retention()==-ENODEV);assert(puts==1&&!adds);
 reset();domain.name="other";assert(enable_display_retention()==-ENODEV);assert(puts==1&&!adds);
 reset();add_error=-EEXIST;assert(enable_display_retention()==-EEXIST);assert(puts==1&&adds==1);
 disable_display_retention();assert(!removes);
 reset();assert(enable_display_retention()==0);assert(retention_active&&firmware_fb);
 assert(retention_nb.notifier_call(0,GENPD_NOTIFY_ON,0)==NOTIFY_OK);assert(!retained);
 assert(retention_nb.notifier_call(0,GENPD_NOTIFY_PRE_OFF,0)==-EBUSY);assert(retained==1);
 disable_display_retention();assert(!retention_active&&!firmware_fb&&removes==1&&puts==1);
 disable_display_retention();assert(removes==1&&puts==1);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as temp:
 p=pathlib.Path(temp);(p/'test.c').write_text(code)
 flags=['-fsanitize=address,undefined'] if '--sanitize' in sys.argv[2:] else []
 subprocess.run(['cc','-Wall','-Wextra','-Wno-unused-parameter',*flags,str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('PASS: retention domain/driver guards, notifier failure, veto, balanced cleanup')
