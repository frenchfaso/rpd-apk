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
#include <linux/platform_device.h>

#define BASE 0x01a94000
#define SIZE 0x300
#define IRQ_MASKS 0xa2220202
static void __iomem *regs;
static struct platform_device *pdev;
static struct backlight_device *bl;
static DEFINE_MUTEX(lock);
static bool faulted;
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

static int update_status(struct backlight_device *bd)
{
 u32 status, ctrl, tpg, length;
 int ret;
 unsigned int brightness = backlight_get_brightness(bd);
 mutex_lock(&lock);
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
 wr(0x17c, 0x80150051 | (brightness << 8));
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
  dev_err(&bd->dev, "DSI command failed (%d); further writes disabled\n", ret);
 }
out:
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
