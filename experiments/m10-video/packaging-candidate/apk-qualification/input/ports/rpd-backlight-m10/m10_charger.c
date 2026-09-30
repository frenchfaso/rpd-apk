// SPDX-License-Identifier: GPL-2.0-only
/* Board-specific OEM termination and qualified ATL thermal thresholds.
 * ONLY 0x1067-68, 0x1094-97 and 0x109a-9b are writable. Lenovo revision
 * 115aa7f0b35f16fda3c7f3b9b08715471849cc25, qpnp-smb5.c/smb5-lib.c.
 * Hard-hot, JEITA enables and current/voltage limits stay unchanged.
 * Cold thresholds match ATL; hard-hot is deliberately still more restrictive.
 * This is not a complete charger/thermal-policy driver.
 * Loading is read-only; existing supply events trigger qualified writes.
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

static int warm_read(unsigned char *value)
{
	return regmap_bulk_read(map, 0x1094, value, 2);
}

static int warm_write(const unsigned char *value)
{
	return regmap_bulk_write(map, 0x1094, value, 2);
}

static int cold_read(unsigned char *value)
{
	return regmap_bulk_read(map, 0x1096, value, 2);
}

static int cold_write(const unsigned char *value)
{
	return regmap_bulk_write(map, 0x1096, value, 2);
}

static int cold_stop_read(unsigned char *value)
{
	return regmap_bulk_read(map, 0x109a, value, 2);
}

static int cold_stop_write(const unsigned char *value)
{
	return regmap_bulk_write(map, 0x109a, value, 2);
}

/* -170 * 10000 / 1525 = -1114 = fba6, signed big-endian. */
static struct charger_transaction transaction = {
	.read = threshold_read, .write = threshold_write,
	.baseline = {0x7b, 0xa4}, .target = {0xfb, 0xa6},
};

/* Exact ATL soft-hot value from the stock M10 battery profile. */
static struct charger_transaction warm_transaction = {
	.read = warm_read, .write = warm_write,
	.baseline = {0x1b, 0xff}, .target = {0x0f, 0xb3},
};

/* Stock ATL soft-cold and hard-cold, respectively. Hardware comparison
 * remains active while CPUs sleep; no userspace temperature loop is needed.
 */
static struct charger_transaction cold_transaction = {
	.read = cold_read, .write = cold_write,
	.baseline = {0x44, 0xc7}, .target = {0x25, 0x7d},
};

static struct charger_transaction cold_stop_transaction = {
	.read = cold_stop_read, .write = cold_stop_write,
	.baseline = {0x4a, 0xff}, .target = {0x37, 0x33},
};

static struct charger_transaction *settings[] = {
	&transaction, &warm_transaction, &cold_transaction, &cold_stop_transaction,
};

static bool dirty(void)
{
	unsigned int i;
	for (i = 0; i < ARRAY_SIZE(settings); i++)
		if (settings[i]->dirty)
			return true;
	return false;
}

static void release_reference(void)
{
	if (!dirty() && pinned) {
		pinned = false;
		module_put(THIS_MODULE);
	}
}

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
		{0x110b, 0x51, 0x11},
		{0x1098, 0xff, 0x15}, {0x1099, 0xff, 0xaa},
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
	 * finishes while CPUs are suspended. Hard-hot protection and JEITA enable
	 * bits are not changed.
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
	int i, ret;
	restore_result = 0;
	/* Restore thermal thresholds before termination. Attempt all on failure. */
	for (i = ARRAY_SIZE(settings) - 1; i >= 0; i--) {
		ret = charger_restore(settings[i]);
		if (ret && !restore_result)
			restore_result = ret;
	}
	pr_info("m10_charger: restore=%d dirty=%d\n", restore_result, dirty());
	if (!dirty()) {
		applied = false;
		__pm_relax(wake);
		release_reference();
	} else {
		__pm_stay_awake(wake);
		mod_delayed_work(system_wq, &rollback_work, 5 * HZ);
	}
}

static void rollback_run(struct work_struct *work)
{
	mutex_lock(&lock);
	if (dirty())
		restore_locked();
	mutex_unlock(&lock);
}

static void update_locked(void)
{
	unsigned char value[2];
	unsigned int i, usb_status;
	bool complete = true;
	int ret;
	if (!enabled)
		return;
	/* Read every setting before any write. Defaults may reset independently; preserve
	 * ownership of the other setting across an unpowered waiting interval.
	 */
	for (i = 0; i < ARRAY_SIZE(settings); i++) {
		struct charger_transaction *t = settings[i];
		ret = t->read(value);
		if (ret) {
			result = ret;
			return;
		}
		if (value[0] == t->target[0] && value[1] == t->target[1])
			continue;
		t->dirty = 0;
		t->verified = 0;
		complete = false;
		if (value[0] != t->baseline[0] || value[1] != t->baseline[1]) {
			enabled = false;
			result = -ESTALE;
			restore_locked();
			pr_err("m10_charger: threshold ownership changed; foreign value preserved\n");
			return;
		}
	}
	release_reference();
	if (applied && complete) {
		result = 0;
		return;
	}
	applied = false;
	ret = regmap_read(map, 0x1310, &usb_status);
	if (ret) {
		result = ret;
		return;
	}
	if (!(usb_status & BIT(4))) {
		result = -EAGAIN;
		return;
	}
	result = ret = guards();
	if (ret)
		return;
	if (!pinned) {
		if (!try_module_get(THIS_MODULE)) {
			result = -ENODEV;
			return;
		}
		pinned = true;
	}
	__pm_stay_awake(wake);
	for (i = 0; i < ARRAY_SIZE(settings); i++) {
		/* A retained owned setting must not lose its original snapshot. */
		if (settings[i]->dirty)
			continue;
		result = ret = charger_apply(settings[i]);
		if (ret)
			break;
	}
	pr_info("m10_charger: apply=%d term=%02x%02x warm=%02x%02x cold=%02x%02x cold_stop=%02x%02x\n",
		result, transaction.observed[0], transaction.observed[1],
		warm_transaction.observed[0], warm_transaction.observed[1],
		cold_transaction.observed[0], cold_transaction.observed[1],
		cold_stop_transaction.observed[0], cold_stop_transaction.observed[1]);
	if (ret) {
		enabled = false;
		restore_locked();
	} else {
		applied = true;
		__pm_relax(wake);
		release_reference();
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
		"applied=%d enabled=%d dirty=%d apply_result=%d restore_result=%d original=%02x%02x observed=%02x%02x warm_original=%02x%02x warm_observed=%02x%02x cold_original=%02x%02x cold_observed=%02x%02x cold_stop_original=%02x%02x cold_stop_observed=%02x%02x\n",
		applied, enabled, dirty(), result, restore_result,
		transaction.original[0], transaction.original[1],
		transaction.observed[0], transaction.observed[1],
		warm_transaction.original[0], warm_transaction.original[1],
		warm_transaction.observed[0], warm_transaction.observed[1],
		cold_transaction.original[0], cold_transaction.original[1],
		cold_transaction.observed[0], cold_transaction.observed[1],
		cold_stop_transaction.original[0], cold_stop_transaction.original[1],
		cold_stop_transaction.observed[0], cold_stop_transaction.observed[1]);
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
MODULE_DESCRIPTION("Guarded Lenovo M10 OEM termination and ATL thermal thresholds");
