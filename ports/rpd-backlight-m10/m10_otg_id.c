// SPDX-License-Identifier: GPL-2.0-only
/* Lenovo stock HSUSB_gpiopull=L16 (1.8V), ID=TLMM124.
 * Diagnostic only: never enables USB VBUS or changes USB role.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/gpio/machine.h>
#include <linux/gpio/driver.h>
#include <linux/pinctrl/consumer.h>
#include <linux/pinctrl/machine.h>
#include <linux/pinctrl/pinconf-generic.h>
#include <linux/regulator/consumer.h>

static struct platform_device *pdev;
static struct gpio_desc *id;
static struct gpio_desc *analog;
static struct regulator *pull;
static struct pinctrl *pins;
static struct pinctrl_state *detect_state, *restore_state;
static unsigned long detect_config[] = { PIN_CONF_PACKED(PIN_CONFIG_BIAS_DISABLE, 0) };
static unsigned long restore_config[] = { PIN_CONF_PACKED(PIN_CONFIG_BIAS_PULL_DOWN, 1) };
static unsigned long analog_config[] = {
 PIN_CONF_PACKED(PIN_CONFIG_BIAS_HIGH_IMPEDANCE, 1),
 PIN_CONF_PACKED(PIN_CONFIG_BIAS_DISABLE, 1),
};
static unsigned long analog_restore[] = {
 PIN_CONF_PACKED(PIN_CONFIG_BIAS_PULL_DOWN, 1),
 PIN_CONF_PACKED(PIN_CONFIG_INPUT_ENABLE, 1),
};
static struct pinctrl_map maps[] = {
 PIN_MAP_CONFIGS_GROUP("m10-otg-id", "detect", "1000000.pinctrl", "gpio124", detect_config),
 PIN_MAP_CONFIGS_GROUP("m10-otg-id", "restore", "1000000.pinctrl", "gpio124", restore_config),
 PIN_MAP_CONFIGS_GROUP("m10-otg-id", "detect", "200f000.spmi:pmic@2:gpio@c000", "gpio1", analog_config),
 PIN_MAP_CONFIGS_GROUP("m10-otg-id", "restore", "200f000.spmi:pmic@2:gpio@c000", "gpio1", analog_restore),
};
static struct gpiod_lookup_table table = {
 .dev_id = "m10-otg-id",
 .table = {
  GPIO_LOOKUP("1000000.pinctrl", 124, "id", GPIO_ACTIVE_HIGH),
  GPIO_LOOKUP("200f000.spmi:pmic@2:gpio@c000", 0, "analog", GPIO_ACTIVE_HIGH),
  {},
 },
};
static int read_id(char *buf, const struct kernel_param *kp)
{
 int value;
 if (!id) return -ENODEV;
 value = gpiod_get_raw_value_cansleep(id);
 if (value < 0) return value;
 return sysfs_emit(buf, "%d\n", value);
}
static const struct kernel_param_ops id_ops = { .get = read_id };
module_param_cb(id, &id_ops, NULL, 0444);
MODULE_PARM_DESC(id, "Physical USB ID signal: low=OTG, high=disconnected/device");

static int __init id_init(void)
{
 int ret;
 if (!of_machine_is_compatible("lenovo,tbx505x")) return -ENODEV;
 pdev = platform_device_register_simple("m10-otg-id", -1, NULL, 0);
 if (IS_ERR(pdev)) return PTR_ERR(pdev);
 ret = pinctrl_register_mappings(maps, ARRAY_SIZE(maps));
 if (ret) goto unregister;
 pins = pinctrl_get(&pdev->dev);
 if (IS_ERR(pins)) { ret = PTR_ERR(pins); goto unmap; }
 detect_state = pinctrl_lookup_state(pins, "detect");
 restore_state = pinctrl_lookup_state(pins, "restore");
 if (IS_ERR(detect_state) || IS_ERR(restore_state)) { ret = -ENODEV; goto put_pins; }
 gpiod_add_lookup_table(&table);
 id = gpiod_get(&pdev->dev, "id", GPIOD_ASIS);
 if (IS_ERR(id)) { ret = PTR_ERR(id); id = NULL; goto device; }
 if (gpiod_get_direction(id) != 1) { ret = -EBUSY; goto gpio; }
 analog = gpiod_get(&pdev->dev, "analog", GPIOD_ASIS);
 if (IS_ERR(analog)) { ret = PTR_ERR(analog); analog = NULL; goto gpio; }
 if (gpiod_get_direction(analog) != 1) {
  ret = -EBUSY; goto gpio;
 }
 pull = regulator_get_optional(&pdev->dev, "l16");
 if (IS_ERR(pull)) { ret = PTR_ERR(pull); pr_err("m10_otg_id: get L16: %d\n",ret); goto gpio; }
 /* Fixed board rail: refuse any unexpected voltage, never program it. */
 if (regulator_get_voltage(pull) != 1800000) { ret = -EINVAL; goto reg; }
 ret = regulator_enable(pull);
 if (ret) { pr_err("m10_otg_id: enable L16: %d\n",ret); goto reg; }
 ret = pinctrl_select_state(pins, detect_state);
 if (ret) { pr_err("m10_otg_id: ID bias: %d\n",ret); goto disable; }
 pr_info("m10_otg_id: stock L16 pull supply enabled at1.8V; ID on GPIO124\n");
 return 0;
disable:
 pinctrl_select_state(pins, restore_state);
 regulator_disable(pull);
reg:
 regulator_put(pull);
gpio:
 if (analog) { gpiod_put(analog); analog = NULL; }
 gpiod_put(id); id = NULL;
device:
 pr_err("m10_otg_id: initialization failed: %d\n",ret);
 gpiod_remove_lookup_table(&table);
put_pins:
 pinctrl_put(pins);
unmap:
 pinctrl_unregister_mappings(maps);
unregister:
 platform_device_unregister(pdev);
 return ret;
}
static void __exit id_exit(void)
{
 if (pinctrl_select_state(pins, restore_state))
  pr_err("m10_otg_id: failed restoring original pull-down\n");
 if (regulator_disable(pull)) pr_err("m10_otg_id: L16 disable failed\n");
 regulator_put(pull);
 gpiod_put(analog);
 gpiod_put(id);
 gpiod_remove_lookup_table(&table);
 pinctrl_put(pins);
 pinctrl_unregister_mappings(maps);
 platform_device_unregister(pdev);
}
module_init(id_init);
module_exit(id_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Temporary Lenovo M10 stock USB ID pull-supply diagnostic");
