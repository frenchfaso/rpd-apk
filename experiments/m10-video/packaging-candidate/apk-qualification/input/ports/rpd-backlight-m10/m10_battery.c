// SPDX-License-Identifier: GPL-2.0-only
/* Bounded read-only PMI632 diagnostic. No register writes, IRQ handling,
 * ADC programming, charging control or battery estimates.
 * Optional standard telemetry exposes only validated measurements.
 * Offsets: Lenovo qg-reg.h and smb5-reg.h, commit
 * 115aa7f0b35f16fda3c7f3b9b08715471849cc25.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>
#include <linux/math64.h>
#include <linux/iio/consumer.h>
#include "m10_battery_temperature.h"

static struct platform_device *anchor;
static struct regmap *map;
static bool telemetry = true;
module_param(telemetry, bool, 0400);
MODULE_PARM_DESC(telemetry, "Expose experimental read-only power_supply telemetry");
static struct power_supply *battery, *usb;
static struct delayed_work poll_work;

static int gauge_value(unsigned int address, bool is_current, int *value)
{
 u8 data[2];
 int ret = regmap_bulk_read(map, address, data, sizeof(data));
 unsigned int raw;
 if (ret) return ret;
 raw = data[0] | data[1] << 8;
 /* Linux ABI: positive = charging, opposite of Qualcomm QG convention. */
 *value = is_current ? -div_s64((s64)(s16)raw * 152588, 1000) :
                       div_u64((u64)raw * 194637, 1000);
 return 0;
}

static int read_iio_voltage(struct power_supply *psy, const char *name, int *value)
{
 struct iio_channel *channel = iio_channel_get(&psy->dev, name);
 int ret;
 if (IS_ERR(channel)) return PTR_ERR(channel);
 ret = iio_read_channel_processed(channel, value);
 iio_channel_release(channel);
 return ret;
}

/* SMB5 STATUS_1 states and STATUS_5 enable bits, as in Lenovo's smb5-lib.
 * Taper is still charging even when its current drops below our noise floor.
 * Keep Full restricted to real termination; inhibit alone is not a reference.
 */
static int m10_charge_status(int current_ua, unsigned int state,
                             bool usb_online, unsigned int enabled)
{
 state &= 7;
 if (usb_online && state == 5 && current_ua >= -20000 && current_ua <= 100000)
  return POWER_SUPPLY_STATUS_FULL;
 if (current_ua < -20000)
  return POWER_SUPPLY_STATUS_DISCHARGING;
 if (usb_online) {
  if (state >= 1 && state <= 4)
   return enabled & 7 ? POWER_SUPPLY_STATUS_CHARGING : POWER_SUPPLY_STATUS_NOT_CHARGING;
  if (state == 0 || state == 6 || state == 7)
   return POWER_SUPPLY_STATUS_NOT_CHARGING;
 }
 return current_ua > 20000 ? POWER_SUPPLY_STATUS_CHARGING : POWER_SUPPLY_STATUS_UNKNOWN;
}

static int battery_get(struct power_supply *psy, enum power_supply_property prop,
                       union power_supply_propval *value)
{
 int ret, current_ua, id_uv, therm_uv;
 unsigned int charge_state, usb_status, charge_enabled;
 switch (prop) {
 case POWER_SUPPLY_PROP_TEMP:
  ret = read_iio_voltage(psy, "battery-id-voltage", &id_uv);
  if (ret) return -ENODATA;
  ret = read_iio_voltage(psy, "battery-therm-voltage", &therm_uv);
  if (ret) return -ENODATA;
  return m10_temperature(id_uv, therm_uv, &value->intval);
 case POWER_SUPPLY_PROP_VOLTAGE_NOW:
  return gauge_value(0x48c0, false, &value->intval);
 case POWER_SUPPLY_PROP_CURRENT_NOW:
  return gauge_value(0x48c2, true, &value->intval);
 case POWER_SUPPLY_PROP_SCOPE:
  value->intval = POWER_SUPPLY_SCOPE_SYSTEM;
  return 0;
 case POWER_SUPPLY_PROP_STATUS:
  ret = gauge_value(0x48c2, true, &current_ua);
  if (ret) return ret;
  ret = regmap_read(map, 0x1006, &charge_state);
  if (ret) return ret;
  ret = regmap_read(map, 0x1310, &usb_status);
  if (ret) return ret;
  ret = regmap_read(map, 0x100b, &charge_enabled);
  if (ret) return ret;
  value->intval = m10_charge_status(current_ua, charge_state,
                                    usb_status & BIT(4), charge_enabled);
  return 0;
 default:
  return -EINVAL;
 }
}

static int usb_get(struct power_supply *psy, enum power_supply_property prop,
                   union power_supply_propval *value)
{
 unsigned int status;
 int ret;
 if (prop != POWER_SUPPLY_PROP_ONLINE) return -EINVAL;
 ret = regmap_read(map, 0x1310, &status);
 if (ret) return ret;
 value->intval = !!(status & BIT(4));
 return 0;
}

static enum power_supply_property battery_props[] = {
 POWER_SUPPLY_PROP_STATUS, POWER_SUPPLY_PROP_VOLTAGE_NOW,
 POWER_SUPPLY_PROP_CURRENT_NOW, POWER_SUPPLY_PROP_SCOPE, POWER_SUPPLY_PROP_TEMP,
};
static enum power_supply_property usb_props[] = { POWER_SUPPLY_PROP_ONLINE };
static const struct power_supply_desc battery_desc = {
 .name = "m10-battery", .type = POWER_SUPPLY_TYPE_BATTERY,
 .properties = battery_props, .num_properties = ARRAY_SIZE(battery_props),
 .get_property = battery_get,
};
static const struct power_supply_desc usb_desc = {
 .name = "m10-usb", .type = POWER_SUPPLY_TYPE_USB,
 .properties = usb_props, .num_properties = ARRAY_SIZE(usb_props),
 .get_property = usb_get,
};

static void poll_supplies(struct work_struct *work)
{
 power_supply_changed(battery);
 power_supply_changed(usb);
 queue_delayed_work(system_freezable_wq, &poll_work, 15 * HZ);
}
struct sample { unsigned int reg, len; };
/* Only known data/configuration and real-time status. No interrupt latches.
 * SDAM and monotonic SOC may be stale Android/bootloader data, not live SOC.
 * Live samples are not latched; consumers must check repeated snapshots.
 */
static const struct sample samples[] = {
 {0x1004, 2}, {0x1006, 2}, {0x100b, 1}, {0x100d, 1},
 {0x1042, 1}, {0x1051, 1}, {0x1061, 1}, {0x1070, 1}, {0x1090, 1},
 {0x1106, 3}, {0x110b, 1}, {0x1140, 1}, {0x1210, 1},
 {0x1310, 1}, {0x1370, 1},
 {0x4804, 2}, {0x4808, 1}, {0x480a, 2},
 {0x4841, 3}, {0x4851, 2}, {0x4870, 8}, {0x48bf, 1},
 {0x48c0, 4}, {0x48c6, 2}, {0x48cc, 2},
 {0xb104, 2}, {0xb146, 8}, {0xb14e, 8}, {0xb156, 2},
 {0xb168, 2}, {0xb1bc, 2},
};

static int snapshot_get(char *buf, const struct kernel_param *kp)
{
 unsigned int i, j;
 unsigned char data[8];
 int ret, n = 0;
 if (!map) return -ENODEV;
 for (i = 0; i < ARRAY_SIZE(samples); ++i) {
  ret = regmap_bulk_read(map, samples[i].reg, data, samples[i].len);
  if (ret) return ret;
  for (j = 0; j < samples[i].len; ++j)
   n += scnprintf(buf + n, PAGE_SIZE - n, "%04x=%02x\n",
                  samples[i].reg + j, data[j]);
 }
 return n;
}
static const struct kernel_param_ops snapshot_ops = { .get = snapshot_get };
module_param_cb(snapshot, &snapshot_ops, NULL, 0400);
MODULE_PARM_DESC(snapshot, "Read-only selected PMI632 gauge and charger registers");

/* A coherent, read-only view of the hardware integration window. Counter
 * movement during a read makes the sample unusable; never hold/reset the gauge.
 * QG_STATUS2 is cleared by an explicit write in OEM qg_read(), not by reading.
 */
static const struct sample qg_samples[] = {
 {0x4808, 3}, {0x4851, 2}, {0x4870, 8}, {0x4888, 7},
 {0x4890, 8}, {0x4898, 8}, {0x48a0, 8}, {0x48a8, 8},
};

static int qg_snapshot_get(char *buf, const struct kernel_param *kp)
{
 unsigned int before_fifo, before_acc, after_fifo, after_acc, i, j;
 unsigned char data[8];
 int ret, n = 0;
 if (!map) return -ENODEV;
 ret = regmap_read(map, 0x480a, &before_fifo);
 if (ret) return ret;
 ret = regmap_read(map, 0x488e, &before_acc);
 if (ret) return ret;
 for (i = 0; i < ARRAY_SIZE(qg_samples); ++i) {
  if (!qg_samples[i].len || qg_samples[i].len > sizeof(data)) return -EINVAL;
  ret = regmap_bulk_read(map, qg_samples[i].reg, data, qg_samples[i].len);
  if (ret) return ret;
  for (j = 0; j < qg_samples[i].len; ++j)
   n += scnprintf(buf + n, PAGE_SIZE - n, "%04x=%02x\n",
                  qg_samples[i].reg + j, data[j]);
 }
 ret = regmap_read(map, 0x480a, &after_fifo);
 if (ret) return ret;
 ret = regmap_read(map, 0x488e, &after_acc);
 if (ret) return ret;
 if (before_fifo != after_fifo || before_acc != after_acc) return -EAGAIN;
 return n;
}
static const struct kernel_param_ops qg_snapshot_ops = { .get = qg_snapshot_get };
module_param_cb(qg_snapshot, &qg_snapshot_ops, NULL, 0400);
MODULE_PARM_DESC(qg_snapshot, "Coherent read-only PMI632 FIFO, accumulator and OCV data");

static int __init probe_init(void)
{
 struct device_node *node;
 unsigned int type;
 int ret = -ENODEV;
 if (!of_machine_is_compatible("lenovo,tbx505x")) return -ENODEV;
 node = of_find_node_by_path("/soc@0/spmi@200f000/pmic@2/temp-alarm@2400");
 if (!node) return -ENODEV;
 anchor = of_find_device_by_node(node);
 of_node_put(node);
 if (!anchor) return -ENODEV;
 if (!anchor->dev.parent ||
     !of_device_is_compatible(anchor->dev.parent->of_node, "qcom,pmi632"))
  goto fail;
 map = dev_get_regmap(anchor->dev.parent, NULL);
 if (!map) goto fail;
 ret = regmap_read(map, 0x4804, &type);
 if (ret) goto fail;
 if (type != 0x0d) { ret = -ENODEV; goto fail; }
 if (telemetry) {
  battery = power_supply_register(&anchor->dev, &battery_desc, NULL);
  if (IS_ERR(battery)) { ret = PTR_ERR(battery); goto fail; }
  usb = power_supply_register(&anchor->dev, &usb_desc, NULL);
  if (IS_ERR(usb)) {
   ret = PTR_ERR(usb);
   power_supply_unregister(battery);
   goto fail;
  }
  INIT_DELAYED_WORK(&poll_work, poll_supplies);
  queue_delayed_work(system_freezable_wq, &poll_work, 15 * HZ);
 }
 pr_info("m10_battery: read-only PMI632 telemetry ready\n");
 return 0;
fail:
 map = NULL;
 put_device(&anchor->dev);
 return ret;
}
static void __exit probe_exit(void)
{
 if (telemetry) {
  cancel_delayed_work_sync(&poll_work);
  power_supply_unregister(usb);
  power_supply_unregister(battery);
 }
 put_device(&anchor->dev);
}
module_init(probe_init);
module_exit(probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Read-only Lenovo M10 PMI632 battery diagnostic");
