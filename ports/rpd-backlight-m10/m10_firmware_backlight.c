// SPDX-License-Identifier: GPL-2.0-only
/* Narrow firmware-handoff driver for Lenovo M10 INX JD9365.
 * Preserves bootloader scanout, PHY, PLL, timings and power supplies.
 * TPG command transport derived from msm89x7-mainline/msm-4.9
 * c348797f41abb995dbdac36d2c6e8324202244d7 mdss_dsi_host.c.
 * Remove this bridge when a native DRM DSI driver becomes available.
 */
#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/ioport.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/pm_domain.h>
#include <linux/platform_device.h>
#include <linux/suspend.h>

/* Lenovo stock INX JD9365 on/off commands, including OEM wait times.
 * Keep supplies and reset untouched: only the panel enters DCS sleep.
 */
struct panel_cmd { u8 type, cmd, value, wait_ms; };
static const struct panel_cmd panel_on[] = {
 { 0x05, 0x11, 0x00, 120 },
 { 0x15, 0xe0, 0x00, 0 },
 { 0x15, 0xe1, 0x93, 0 },
 { 0x15, 0xe2, 0x65, 0 },
 { 0x15, 0xe3, 0xf8, 0 },
 { 0x15, 0x80, 0x03, 0 },
 { 0x15, 0xe0, 0x03, 0 },
 { 0x15, 0xa0, 0x33, 0 },
 { 0x15, 0xa1, 0x11, 0 },
 { 0x15, 0xe0, 0x01, 0 },
 { 0x15, 0x37, 0x15, 0 },
 { 0x15, 0xe0, 0x00, 0 },
 { 0x05, 0x29, 0x00, 10 },
 { 0x15, 0x51, 0x00, 0 },
 { 0x15, 0x53, 0x2c, 0 },
 { 0x15, 0x55, 0x00, 0 },
};
static const struct panel_cmd panel_off[] = {
 { 0x15, 0x53, 0x24, 0 },
 { 0x15, 0x51, 0x00, 0 },
 { 0x15, 0x55, 0x10, 0 },
 { 0x05, 0x28, 0x00, 20 },
 { 0x05, 0x10, 0x00, 120 },
};


#define BASE 0x01a94000
#define SIZE 0x300
#define IRQ_MASKS 0xa2220202
/* Firmware scanout cannot be reconstructed after MDSS power collapse.
 * Keep only its domain on through the supported genpd notifier veto. This
 * trades suspend power for working resume until a native DRM driver takes over.
 * Never edit genpd flags or program clocks/voltages behind their drivers.
 */
static struct platform_device *firmware_fb;
static bool retain_display = true;
module_param(retain_display, bool, 0444);
MODULE_PARM_DESC(retain_display, "Preserve firmware display power domain across suspend");
static bool retention_active;
module_param(retention_active, bool, 0444);
static unsigned int retained;
module_param(retained, uint, 0444);

static int retain_display_power(struct notifier_block *nb, unsigned long event, void *data)
{
 if (event != GENPD_NOTIFY_PRE_OFF) return NOTIFY_OK;
 retained++;
 return notifier_from_errno(-EBUSY);
}
static struct notifier_block retention_nb = { .notifier_call = retain_display_power };

static int enable_display_retention(void)
{
 struct device_node *node;
 struct generic_pm_domain *pd;
 int ret;
 if (!retain_display) return 0;
 node = of_find_compatible_node(NULL, NULL, "simple-framebuffer");
 if (!node) return -ENODEV;
 firmware_fb = of_find_device_by_node(node);
 of_node_put(node);
 if (!firmware_fb) return -ENODEV;
 if (!firmware_fb->dev.driver ||
     strcmp(firmware_fb->dev.driver->name, "simple-framebuffer") ||
     !dev_pm_genpd_is_on(&firmware_fb->dev)) { ret = -ENODEV; goto put; }
 /* is_on() first validates that this device actually belongs to genpd. */
 pd = pd_to_genpd(firmware_fb->dev.pm_domain);
 if (strcmp(pd->name, "mdss_gdsc")) { ret = -ENODEV; goto put; }
 ret = dev_pm_genpd_add_notifier(&firmware_fb->dev, &retention_nb);
 if (ret) goto put;
 retention_active = true;
 return 0;
put:
 put_device(&firmware_fb->dev);
 firmware_fb = NULL;
 return ret;
}

static void disable_display_retention(void)
{
 if (!retention_active) return;
 dev_pm_genpd_remove_notifier(&firmware_fb->dev);
 retention_active = false;
 put_device(&firmware_fb->dev);
 firmware_fb = NULL;
}

static void __iomem *regs;
static struct platform_device *pdev;
static struct backlight_device *bl;
static DEFINE_MUTEX(lock);
static bool faulted;
static bool panel_asleep;
module_param(panel_asleep, bool, 0444);
static unsigned int panel_sleeps, panel_wakes;
module_param(panel_sleeps, uint, 0444);
module_param(panel_wakes, uint, 0444);
static char *panel;
module_param(panel, charp, 0444);
MODULE_PARM_DESC(panel, "Required verified panel: inx-jd9365-800p");
static unsigned int initial_brightness = 32;
module_param(initial_brightness, uint, 0444);
MODULE_PARM_DESC(initial_brightness, "Initial DCS level (1..255), restored later by systemd-backlight");

static u32 rd(unsigned int off) { return readl(regs + off); }
static void wr(unsigned int off, u32 value) { writel(value, regs + off); }

static bool firmware_state_valid(void)
{
 return rd(0) == 0x10040002 && rd(4) == 0x1f3 &&
        rd(0x3c) == 0x14000000 && rd(0x15c) == 4 && rd(0x84) == 4 &&
        !(rd(0x110) & (IRQ_MASKS | BIT(24))) && !(rd(8) & 3);
}

static int send_short(u8 type, u8 command, u8 value)
{
 u32 status, ctrl, tpg, length;
 int ret;

 if (faulted || !firmware_state_valid()) {
  ret = -EIO;
  goto out;
 }
 ctrl = rd(4); tpg = rd(0x15c); length = rd(0x4c);
 /* Fresh video completion and skip the initial blanking interval. */
 wr(0x110, BIT(16));
 ret = readl_poll_timeout(regs + 0x110, status, status & BIT(16), 100, 100000);
 if (ret) goto fail;
 usleep_range(1000, 1100);
 wr(4, ctrl | BIT(2));
 wr(0x110, BIT(0));
 wr(0x15c, 0x30006);
 wr(0x17c, BIT(31) | ((u32)type << 16) | ((u32)value << 8) | command);
 wr(0x17c, 0); /* even number of FIFO words required */
 wr(0x4c, 4);
 /* readback orders register setup before triggering the FIFO */
 rd(0x4c);
 wr(0x90, 1);
 ret = readl_poll_timeout(regs + 0x110, status, status & BIT(0), 100, 200000);
 if (!ret && (status & BIT(24)))
  ret = -EIO;
 wr(0x1ec, 1); rd(0x1ec); wr(0x1ec, 0); rd(0x1ec);
 wr(0x15c, tpg); wr(0x4c, length); wr(4, ctrl);
 wr(0x110, status & BIT(0));
 rd(4);
fail:
 if (ret) {
  faulted = true;
  dev_err(&pdev->dev, "DSI command failed (%d); further writes disabled\n", ret);
 }
out:
 return ret;
}

/* Exact panel commands and delays from the stock Lenovo device tree. */
static int set_panel_sleep(bool sleep)
{
 const struct panel_cmd *seq = sleep ? panel_off : panel_on;
 size_t count = sleep ? ARRAY_SIZE(panel_off) : ARRAY_SIZE(panel_on);
 int ret = 0;
 size_t i;
 if (sleep == panel_asleep) return 0;
 for (i = 0; i < count; i++) {
  ret = send_short(seq[i].type, seq[i].cmd, seq[i].value);
  if (ret) return ret;
  if (seq[i].wait_ms) msleep(seq[i].wait_ms);
 }
 panel_asleep = sleep;
 if (sleep) panel_sleeps++;
 else {
  ret = send_short(0x15, 0x51, backlight_get_brightness(bl));
  if (!ret) panel_wakes++;
 }
 return ret;
}
/* Preserve controller state; only the qualified panel enters DCS sleep. */
static bool panel_pm_registered;
static int panel_pm_notify(struct notifier_block *nb, unsigned long event, void *unused)
{
 int ret = 0;
 if (event != PM_SUSPEND_PREPARE && event != PM_POST_SUSPEND) return NOTIFY_OK;
 mutex_lock(&lock);
 if (retention_active)
  ret = set_panel_sleep(event == PM_SUSPEND_PREPARE);
 mutex_unlock(&lock);
 if (ret) {
  dev_err(&pdev->dev, "Panel sleep transition failed (%d)\n", ret);
  return notifier_from_errno(ret);
 }
 return NOTIFY_OK;
}
static struct notifier_block panel_pm_nb = { .notifier_call = panel_pm_notify };
static int update_status(struct backlight_device *bd)
{
 int ret = 0;
 mutex_lock(&lock);
 if (!panel_asleep) ret = send_short(0x15, 0x51, backlight_get_brightness(bd));
 mutex_unlock(&lock);
 return ret;
}

/* Raspberry Pi raindrop discovers panel backlights through this attribute.
 * This firmware framebuffer is exposed as Unknown-1 by simpledrm. */
static ssize_t display_name_show(struct device *dev, struct device_attribute *attr,
                                char *buf)
{
 return sysfs_emit(buf, "Unknown-1\n");
}
static DEVICE_ATTR_RO(display_name);

static const struct backlight_ops ops = { .update_status = update_status };

static int __init m10_bl_init(void)
{
 struct device_node *root, *fb;
 struct backlight_properties props = { .type = BACKLIGHT_RAW, .max_brightness = 255 };
 const char *model;
 int ret;
 bool correct_model;
 root = of_find_node_by_path("/");
 correct_model = root && !of_property_read_string(root, "model", &model) &&
                 !strcmp(model, "Lenovo Tab M10 HD");
 of_node_put(root);
 if (!correct_model || !panel || strcmp(panel, "inx-jd9365-800p") ||
     !initial_brightness || initial_brightness > 255) return -ENODEV;
 fb = of_find_compatible_node(NULL, NULL, "simple-framebuffer");
 if (!fb) return -ENODEV;
 of_node_put(fb);
 /* Never coexist with an owner of the native DSI register range. */
 if (!request_mem_region(BASE, SIZE, "m10-firmware-backlight")) return -EBUSY;
 regs = ioremap(BASE, SIZE);
 if (!regs) { ret = -ENOMEM; goto region; }
 if (!firmware_state_valid()) { ret = -ENODEV; goto unmap; }
 pdev = platform_device_register_simple("m10-firmware-backlight", -1, NULL, 0);
 if (IS_ERR(pdev)) { ret = PTR_ERR(pdev); goto unmap; }
 props.brightness = initial_brightness;
 bl = backlight_device_register("m10_backlight", &pdev->dev, NULL, &ops, &props);
 if (IS_ERR(bl)) { ret = PTR_ERR(bl); goto device; }
 ret = device_create_file(&bl->dev, &dev_attr_display_name);
 if (ret) { backlight_device_unregister(bl); goto device; }
 ret = backlight_update_status(bl);
 if (ret) { backlight_device_unregister(bl); goto device; }
 ret = enable_display_retention();
 if (ret)
  dev_warn(&pdev->dev, "Display retention unavailable (%d); suspend may lose scanout\n", ret);
 else if (retention_active)
  dev_info(&pdev->dev, "Firmware display retention active; higher suspend power expected\n");
 if (retention_active) {
  ret = register_pm_notifier(&panel_pm_nb);
  if (ret) dev_warn(&pdev->dev, "Panel sleep unavailable (%d)\n", ret);
  else panel_pm_registered = true;
 }
 dev_info(&pdev->dev, "Firmware DSI backlight registered, range 0..255\n");
 return 0;
device:
 platform_device_unregister(pdev);
unmap:
 iounmap(regs);
region:
 release_mem_region(BASE, SIZE);
 return ret;
}
static void __exit m10_bl_exit(void)
{
 if (panel_pm_registered) unregister_pm_notifier(&panel_pm_nb);
 mutex_lock(&lock);
 if (panel_asleep) set_panel_sleep(false);
 mutex_unlock(&lock);
 disable_display_retention();
 device_remove_file(&bl->dev, &dev_attr_display_name);
 backlight_device_unregister(bl);
 platform_device_unregister(pdev);
 iounmap(regs);
 release_mem_region(BASE, SIZE);
}
module_init(m10_bl_init);
module_exit(m10_bl_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Lenovo M10 firmware-initialized DSI backlight bridge");
