// SPDX-License-Identifier: GPL-2.0-only
/* Board-specific OEM ADC termination threshold, not a full charger driver.
 * ONLY 0x1067-68 is writable. Lenovo revision
 * 115aa7f0b35f16fda3c7f3b9b08715471849cc25, qpnp-smb5.c, -170 mA.
 * Loading is read-only; the service applies after checking kernel ownership.
 * Existing power-supply events trigger configuration when USB is powered.
 * No dedicated polling or held wake lock is needed during normal operation.
 */
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/power_supply.h>
#include <linux/pm_wakeup.h>
#include <linux/workqueue.h>
#include <linux/mutex.h>
#include <linux/iio/consumer.h>
#include <linux/suspend.h>
#include "m10_charger_transaction.h"

static struct platform_device *anchor;
static struct power_supply *battery;
static struct regmap *map;
static struct wakeup_source *wake;
static DEFINE_MUTEX(lock);
static struct delayed_work rollback_work;
static bool ready, enabled, pinned, applied;
static struct work_struct supply_work;
static int result, restore_result;

static int threshold_read(unsigned char *value)
{
	return regmap_bulk_read(map, 0x1067, value, 2);
}

static int threshold_write(const unsigned char *value)
{
	return regmap_bulk_write(map, 0x1067, value, 2);
}

static struct term_transaction transaction = {
	.read = threshold_read, .write = threshold_write,
};

static int range(enum power_supply_property prop, int low, int high)
{
	union power_supply_propval value;
	int ret = power_supply_get_property(battery, prop, &value);
	if (ret)
		return ret;
	return value.intval < low || value.intval > high ? -ERANGE : 0;
}

static int guards(void)
{
	static const struct { unsigned int reg, mask, value; } checks[] = {
		{0x1004, 0xff, 0x02}, {0x1005, 0xff, 0x80},
		{0x10c0, 0xff, 0x04}, {0x1069, 0xff, 0x01},
		{0x106a, 0xff, 0x46}, {0x1061, 0xff, 0x14},
		{0x1070, 0xff, 0x4b}, {0x1051, 0xff, 0x2c},
		{0x1090, 0xff, 0x1f}, {0x1140, 0x01, 0x00},
		{0x1094, 0xff, 0x1b}, {0x1095, 0xff, 0xff},
		{0x1096, 0xff, 0x44}, {0x1097, 0xff, 0xc7},
		{0x1098, 0xff, 0x15}, {0x1099, 0xff, 0xaa},
		{0x109a, 0xff, 0x4a}, {0x109b, 0xff, 0xff},
		{0x1007, 0x02, 0x00}, {0x100d, 0x0f, 0x00},
	};
	struct iio_channel *channel;
	unsigned int i, value;
	int ret, id_uv;
	for (i = 0; i < ARRAY_SIZE(checks); i++) {
		ret = regmap_read(map, checks[i].reg, &value);
		if (ret)
			return ret;
		if ((value & checks[i].mask) != checks[i].value)
			return -EPERM;
	}
	/* Configuration uses the OEM value without a charge-state/current
	 * requirement. The comparator must already be configured when a charge
	 * finishes while CPUs are suspended. Thermal policy is not changed.
	 */
	ret = range(POWER_SUPPLY_PROP_TEMP, 200, 350);
	if (ret)
		return ret;
	ret = range(POWER_SUPPLY_PROP_VOLTAGE_NOW, 3000000, 4400000);
	if (ret)
		return ret;
	channel = iio_channel_get(&battery->dev, "battery-id-voltage");
	if (IS_ERR(channel))
		return PTR_ERR(channel);
	ret = iio_read_channel_processed(channel, &id_uv);
	iio_channel_release(channel);
	if (ret)
		return ret;
	return id_uv >= 650000 && id_uv <= 700000 ? 0 : -ENODEV;
}

/* Unload cannot bypass restoration. Only an error retry holds a wake lock;
 * successful configuration has no timer, polling or sleep inhibitor.
 */
static void restore_locked(void)
{
	restore_result = term_restore(&transaction);
	pr_info("m10_charger: restore=%d dirty=%d\n",
		restore_result, transaction.dirty);
	if (!transaction.dirty) {
		applied = false;
		__pm_relax(wake);
		if (pinned) {
			pinned = false;
			module_put(THIS_MODULE);
		}
	} else {
		__pm_stay_awake(wake);
		mod_delayed_work(system_wq, &rollback_work, 5 * HZ);
	}
}

static void rollback_run(struct work_struct *work)
{
	mutex_lock(&lock);
	if (transaction.dirty)
		restore_locked();
	mutex_unlock(&lock);
}

static void update_locked(void)
{
	unsigned char value[2];
	unsigned int usb_status;
	int ret;
	if (!enabled)
		return;
	if (transaction.dirty && !applied) {
		enabled = false;
		result = -EBUSY;
		return;
	}
	/* A charger power cycle can restore defaults. Never overwrite a third
	 * value: that belongs to another owner or an unqualified configuration.
	 */
	if (applied) {
		ret = threshold_read(value);
		if (ret) {
			result = ret;
			return;
		}
		if (value[0] == 0xfb && value[1] == 0xa6)
			return;
		transaction.dirty = 0;
		transaction.verified = 0;
		applied = false;
		if (pinned) {
			pinned = false;
			module_put(THIS_MODULE);
		}
		if (value[0] != 0x7b || value[1] != 0xa4) {
			enabled = false;
			result = -ESTALE;
			pr_err("m10_charger: threshold ownership changed; no write\n");
			return;
		}
	}
	ret = regmap_read(map, 0x1310, &usb_status);
	if (ret) {
		result = ret;
		return;
	}
	/* The real device ignores configuration writes with USB input absent.
	 * Wait for existing m10-usb notifications; do not hold CPUs awake.
	 */
	if (!(usb_status & BIT(4))) {
		result = -EAGAIN;
		return;
	}
	result = ret = guards();
	if (ret)
		return;
	if (!try_module_get(THIS_MODULE)) {
		result = -ENODEV;
		return;
	}
	pinned = true;
	__pm_stay_awake(wake);
	result = ret = term_apply(&transaction);
	pr_info("m10_charger: apply=%d original=%02x%02x observed=%02x%02x\n",
		result, transaction.original[0], transaction.original[1],
		transaction.observed[0], transaction.observed[1]);
	if (ret) {
		/* A real write failure is latched until the service is restarted. */
		enabled = false;
		restore_locked();
	} else {
		applied = true;
		__pm_relax(wake);
		if (!transaction.dirty) {
			pinned = false;
			module_put(THIS_MODULE);
		}
	}
}

static void supply_changed(struct work_struct *work)
{
	mutex_lock(&lock);
	update_locked();
	mutex_unlock(&lock);
}

static int supply_notify(struct notifier_block *nb, unsigned long event, void *data)
{
	struct power_supply *psy = data;
	if (event == PSY_EVENT_PROP_CHANGED &&
	    !strcmp(psy->desc->name, "m10-usb"))
		queue_work(system_freezable_wq, &supply_work);
	return NOTIFY_OK;
}

static struct notifier_block supply_notifier = { .notifier_call = supply_notify };

static int power_notify(struct notifier_block *nb, unsigned long event, void *data)
{
	/* Close the interval between plugging USB and the next gauge notification
	 * when Power is pressed immediately afterwards. IIO is still available.
	 */
	if (event == PM_SUSPEND_PREPARE || event == PM_POST_SUSPEND) {
		mutex_lock(&lock);
		update_locked();
		mutex_unlock(&lock);
	}
	return NOTIFY_OK;
}

static struct notifier_block power_notifier = { .notifier_call = power_notify };

static int control_set(const char *text, const struct kernel_param *kp)
{
	bool start;
	int ret = kstrtobool(text, &start);
	if (ret)
		return ret;
	mutex_lock(&lock);
	if (!ready) {
		ret = -ENODEV;
		goto out;
	}
	enabled = start;
	if (!start) {
		restore_locked();
		ret = restore_result;
	} else {
		update_locked();
		/* Waiting for USB or guard conditions is not an apply failure. */
		ret = enabled ? 0 : result;
	}
out:
	mutex_unlock(&lock);
	return ret;
}

static int status_get(char *buf, const struct kernel_param *kp)
{
	int n;
	mutex_lock(&lock);
	n = scnprintf(buf, PAGE_SIZE,
		"applied=%d enabled=%d dirty=%d apply_result=%d restore_result=%d original=%02x%02x observed=%02x%02x\n",
		applied, enabled, transaction.dirty, result, restore_result,
		transaction.original[0], transaction.original[1],
		transaction.observed[0], transaction.observed[1]);
	mutex_unlock(&lock);
	return n;
}

static const struct kernel_param_ops control_ops = { .set = control_set };
static const struct kernel_param_ops status_ops = { .get = status_get };
module_param_cb(control, &control_ops, NULL, 0200);
module_param_cb(status, &status_ops, NULL, 0400);

static int __init charger_init(void)
{
	struct device_node *node;
	int ret = -ENODEV;
	if (!of_machine_is_compatible("lenovo,tbx505x"))
		return ret;
	node = of_find_node_by_path("/soc@0/spmi@200f000/pmic@2/temp-alarm@2400");
	if (!node)
		return ret;
	anchor = of_find_device_by_node(node);
	of_node_put(node);
	if (!anchor)
		return ret;
	if (!anchor->dev.parent ||
	    !of_device_is_compatible(anchor->dev.parent->of_node, "qcom,pmi632"))
		goto fail;
	map = dev_get_regmap(anchor->dev.parent, NULL);
	if (!map)
		goto fail;
	battery = power_supply_get_by_name("m10-battery");
	if (!battery)
		goto fail;
	wake = wakeup_source_register(NULL, "m10-charger-rollback");
	if (!wake) {
		power_supply_put(battery);
		ret = -ENOMEM;
		goto fail;
	}
	INIT_DELAYED_WORK(&rollback_work, rollback_run);
	INIT_WORK(&supply_work, supply_changed);
	ret = power_supply_reg_notifier(&supply_notifier);
	if (ret) {
		wakeup_source_unregister(wake);
		power_supply_put(battery);
		goto fail;
	}
	ret = register_pm_notifier(&power_notifier);
	if (ret) {
		power_supply_unreg_notifier(&supply_notifier);
		cancel_work_sync(&supply_work);
		wakeup_source_unregister(wake);
		power_supply_put(battery);
		goto fail;
	}
	ready = true;
	pr_info("m10_charger: loaded without changing hardware\n");
	return 0;
fail:
	put_device(&anchor->dev);
	return ret;
}

static void __exit charger_exit(void)
{
	/* Active or unverified rollback holds a module reference: rmmod is busy. */
	unregister_pm_notifier(&power_notifier);
	power_supply_unreg_notifier(&supply_notifier);
	cancel_work_sync(&supply_work);
	cancel_delayed_work_sync(&rollback_work);
	wakeup_source_unregister(wake);
	power_supply_put(battery);
	put_device(&anchor->dev);
}
module_init(charger_init);
module_exit(charger_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Guarded Lenovo M10 OEM ADC charge-termination threshold");
