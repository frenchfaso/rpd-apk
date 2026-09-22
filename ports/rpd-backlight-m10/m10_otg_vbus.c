// SPDX-License-Identifier: GPL-2.0-only
/* Temporary M10 PMI632 adapter for upstream qcom_usb_vbus-regulator.c.
 * Register definitions/operations: Copyright (c) 2020, The Linux Foundation.
 * No charger configuration, voltage programming, or DT replacement.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/consumer.h>
#include <linux/regulator/machine.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <linux/delay.h>

#define CMD 0x1140
#define LIMIT 0x1152
#define CFG 0x1153
static struct platform_device *anchor, *pdev;
static struct regmap *map;
static struct regulator_dev *rdev;
static struct regulator *supply;
static unsigned int old_limit, old_cfg;
static bool saved;
static bool board_route;
module_param(board_route, bool, 0400);
MODULE_PARM_DESC(board_route, "Enable Lenovo GPIO130 dock isolation and GPIO94 OTG path; no dock attached");
/* Stock SDM429 DT and Lenovo phy-msm-usb.c at commit115aa7f0:
 * GPIO130=1 isolates pogo; GPIO94=1 precedes VBUS by50ms.
 * This bounded probe only accepts the observed input-low initial state.
 */
static struct gpiod_lookup_table route_table = {
 .dev_id = "m10-otg-vbus",
 .table = {
  GPIO_LOOKUP_IDX("1000000.pinctrl",130,"route",0,GPIO_ACTIVE_HIGH),
  GPIO_LOOKUP_IDX("1000000.pinctrl",94,"route",1,GPIO_ACTIVE_HIGH),
  {},
 },
};
static struct gpio_desc *route[2];
static bool route_changed[2], lookup_added;
static void route_restore(void)
{
 int i;
 for(i=1;i>=0;i--) {
  if(!route[i]) continue;
  if(route_changed[i]) {
   gpiod_set_value_cansleep(route[i],0);
   if(gpiod_direction_input(route[i]))
    pr_err("m10_otg: GPIO route%d input restoration failed\n",i);
   route_changed[i]=false;
  }
  gpiod_put(route[i]); route[i]=NULL;
 }
 if(lookup_added) {
  gpiod_remove_lookup_table(&route_table); lookup_added=false;
 }
}
static int route_enable(void)
{
 int i,ret;
 if(!board_route) return 0;
 gpiod_add_lookup_table(&route_table); lookup_added=true;
 for(i=0;i<2;i++) {
  route[i]=gpiod_get_index(&pdev->dev,"route",i,GPIOD_ASIS);
  if(IS_ERR(route[i])) {ret=PTR_ERR(route[i]);route[i]=NULL;goto fail;}
  if(gpiod_get_direction(route[i])!=1 || gpiod_get_raw_value_cansleep(route[i])!=0) {
   ret=-EBUSY; goto fail;
  }
 }
 for(i=0;i<2;i++) {
  route_changed[i]=true;
  ret=gpiod_direction_output(route[i],1);
  if(ret) goto fail;
 }
 msleep(50);
 pr_info("m10_otg: Lenovo GPIO130 and GPIO94 route enabled\n");
 return 0;
fail: route_restore(); return ret;
}
/* A consumer pins its provider module. Release it explicitly before rmmod. */
static bool stopped;
static int stop_set(const char *value, const struct kernel_param *kp)
{
 bool stop;
 int ret=kstrtobool(value,&stop);
 if(ret) return ret;
 if(!stop) return -EINVAL;
 if(stopped) return 0;
 if(!supply || IS_ERR(supply)) return -ENODEV;
 ret=regulator_disable(supply);
 if(ret) return ret;
 msleep(50);
 route_restore();
 regulator_put(supply);supply=NULL;stopped=true;
 pr_info("m10_otg: VBUS stopped; module may now be removed\n");
 return 0;
}
static const struct kernel_param_ops stop_ops={.set=stop_set,.get=param_get_bool};
module_param_cb(stop,&stop_ops,&stopped,0600);
MODULE_PARM_DESC(stop,"Write1 to turn off VBUS and release the internal consumer before rmmod");
static bool otg_cable;
module_param(otg_cable, bool, 0400);
MODULE_PARM_DESC(otg_cable, "Required: OTG adapter with peripherals only, no charger/PC");
static const unsigned int currents[] = {500000,1000000,1500000,2000000,2500000,3000000};
static const struct regulator_ops ops = {
 .enable=regulator_enable_regmap, .disable=regulator_disable_regmap,
 .is_enabled=regulator_is_enabled_regmap,
 .get_current_limit=regulator_get_current_limit_regmap,
 .set_current_limit=regulator_set_current_limit_regmap,
};
static const struct regulator_desc desc = {
 .name="m10-otg-vbus", .ops=&ops, .owner=THIS_MODULE,
 .type=REGULATOR_VOLTAGE, .curr_table=currents, .n_current_limits=ARRAY_SIZE(currents),
 .enable_reg=CMD, .enable_mask=BIT(0), .csel_reg=LIMIT, .csel_mask=GENMASK(2,0),
};
static struct regulator_init_data init_data = {
 .constraints={.name="m10-otg-vbus", .min_uA=500000, .max_uA=500000,
 .valid_ops_mask=REGULATOR_CHANGE_STATUS|REGULATOR_CHANGE_CURRENT},
};
static void restore(void)
{
 if (saved) {
  int a=regmap_update_bits(map,LIMIT,GENMASK(2,0),old_limit);
  int b=regmap_update_bits(map,CFG,BIT(1),old_cfg);
  if (a || b)
   pr_err("m10_otg: could not restore VBUS settings\n");
 }
}
static int __init m10_init(void)
{
 struct device_node *node, *vbus;
 struct regulator_config config={};
 unsigned int cmd;
 int ret;
 if (!otg_cable || !of_machine_is_compatible("lenovo,tbx505x")) {pr_err("m10_otg: board/cable guard failed\n");return -ENODEV;}
 node=of_find_node_by_path("/soc@0/spmi@200f000/pmic@2/temp-alarm@2400");
 if (!node) {pr_err("m10_otg: anchor node missing\n");return -ENODEV;}
 anchor=of_find_device_by_node(node); of_node_put(node);
 if (!anchor) {pr_err("m10_otg: anchor device missing\n");return -ENODEV;}
 if (!anchor->dev.parent || !of_device_is_compatible(anchor->dev.parent->of_node,"qcom,pmi632")) {
  ret=-ENODEV; goto put;
 }
 vbus=of_find_node_by_path("/soc@0/spmi@200f000/pmic@2/usb-vbus-regulator@1100");
 if (!vbus) {ret=-ENODEV;goto put;}
 ret=of_device_is_available(vbus) ? -EBUSY : 0;
 of_node_put(vbus);
 if(ret) goto put;
 map=dev_get_regmap(anchor->dev.parent,NULL);
 if(!map) {ret=-ENODEV;goto put;}
 ret=regmap_read(map,CMD,&cmd); if(ret) goto put;
 if(cmd & BIT(0)) {ret=-EBUSY;goto put;}
 ret=regmap_read(map,LIMIT,&old_limit); if(ret) goto put;
 ret=regmap_read(map,CFG,&old_cfg); if(ret) goto put;
 saved=true;
 pr_info("m10_otg: VBUS initially off, limit=%02x cfg=%02x; using 500mA\n",old_limit,old_cfg);
 pdev=platform_device_register_simple("m10-otg-vbus",-1,NULL,0);
 if(IS_ERR(pdev)) {ret=PTR_ERR(pdev);goto put;}
 config.dev=&pdev->dev;config.regmap=map;config.init_data=&init_data;
 rdev=regulator_register(&pdev->dev,&desc,&config);
 if(IS_ERR(rdev)) {ret=PTR_ERR(rdev);goto device;}
 ret=regmap_update_bits(map,CFG,BIT(1),0);if(ret)goto reg;
 supply=regulator_get_optional(&pdev->dev,"m10-otg-vbus");
 if(IS_ERR(supply)){ret=PTR_ERR(supply);goto reg;}
 ret=regulator_set_current_limit(supply,500000,500000);if(ret)goto consumer;
 ret=route_enable();if(ret)goto consumer;
 ret=regulator_enable(supply);if(ret)goto consumer;
 pr_info("m10_otg: VBUS enabled with upstream regulator operations at 500mA\n");
 return 0;
consumer: route_restore();regulator_put(supply);
reg: regulator_unregister(rdev);
device: restore();platform_device_unregister(pdev);
put: pr_err("m10_otg: initialization stopped: %d\n",ret);put_device(&anchor->dev); return ret;
}
static void __exit m10_exit(void)
{
 if(supply) {
  if(regulator_disable(supply)) pr_err("m10_otg: VBUS disable failed\n");
  regulator_put(supply);
 }
 route_restore();
 regulator_unregister(rdev);restore();
 platform_device_unregister(pdev);put_device(&anchor->dev);
}
module_init(m10_init);module_exit(m10_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Temporary M10 PMI632 VBUS 500mA regulator adapter");
