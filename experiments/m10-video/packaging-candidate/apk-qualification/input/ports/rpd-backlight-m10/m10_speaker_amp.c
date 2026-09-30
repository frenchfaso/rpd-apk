// SPDX-License-Identifier: GPL-2.0-only
/*
 * TB-X505L speaker amplifier enable protocol, recovered from the stock
 * audio_machine_sdm450.ko msm_spk_switch SPKL/SPKR paths. Each amplifier
 * uses two rising edges, 2 us apart. The physical amplifier part is unknown.
 * DAPM integration follows sound/soc/codecs/aw8738.c.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <sound/soc.h>

struct m10_amp {
	struct gpio_desc *enable;
};

static void m10_amp_off(void *data)
{
	struct m10_amp *amp = data;

	gpiod_set_value(amp->enable, 0);
}

static int m10_amp_event(struct snd_soc_dapm_widget *w,
			 struct snd_kcontrol *kcontrol, int event)
{
	struct snd_soc_component *c = snd_soc_dapm_to_component(w->dapm);
	struct m10_amp *amp = snd_soc_component_get_drvdata(c);
	unsigned long flags;
	int i;

	switch (event) {
	case SND_SOC_DAPM_POST_PMU:
		local_irq_save(flags);
		for (i = 0; i < 2; i++) {
			gpiod_set_value(amp->enable, 0);
			udelay(2);
			gpiod_set_value(amp->enable, 1);
			udelay(2);
		}
		local_irq_restore(flags);
		msleep(40);
		break;
	case SND_SOC_DAPM_PRE_PMD:
		m10_amp_off(amp);
		usleep_range(1000, 2000);
		break;
	default:
		return -EINVAL;
	}
	return 0;
}

static const struct snd_soc_dapm_widget m10_amp_widgets[] = {
	SND_SOC_DAPM_INPUT("IN"),
	SND_SOC_DAPM_OUT_DRV_E("DRV", SND_SOC_NOPM, 0, 0, NULL, 0,
		m10_amp_event, SND_SOC_DAPM_POST_PMU | SND_SOC_DAPM_PRE_PMD),
	SND_SOC_DAPM_OUTPUT("OUT"),
};

static const struct snd_soc_dapm_route m10_amp_routes[] = {
	{ "DRV", NULL, "IN" },
	{ "OUT", NULL, "DRV" },
};

static const struct snd_soc_component_driver m10_amp_component = {
	.dapm_widgets = m10_amp_widgets,
	.num_dapm_widgets = ARRAY_SIZE(m10_amp_widgets),
	.dapm_routes = m10_amp_routes,
	.num_dapm_routes = ARRAY_SIZE(m10_amp_routes),
};

static int m10_amp_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct m10_amp *amp;
	int ret;

	if (!of_machine_is_compatible("lenovo,tbx505x"))
		return -ENODEV;
	amp = devm_kzalloc(dev, sizeof(*amp), GFP_KERNEL);
	if (!amp)
		return -ENOMEM;
	amp->enable = devm_gpiod_get(dev, "enable", GPIOD_OUT_LOW);
	if (IS_ERR(amp->enable))
		return dev_err_probe(dev, PTR_ERR(amp->enable), "enable GPIO\n");
	if (gpiod_cansleep(amp->enable))
		return -EINVAL;
	ret = devm_add_action_or_reset(dev, m10_amp_off, amp);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, amp);
	return devm_snd_soc_register_component(dev, &m10_amp_component, NULL, 0);
}

static void m10_amp_shutdown(struct platform_device *pdev)
{
	m10_amp_off(platform_get_drvdata(pdev));
}

static const struct of_device_id m10_amp_match[] = {
	{ .compatible = "lenovo,tbx505-speaker-amp" },
	{ }
};
MODULE_DEVICE_TABLE(of, m10_amp_match);

static struct platform_driver m10_amp_driver = {
	.probe = m10_amp_probe,
	.shutdown = m10_amp_shutdown,
	.driver = {
		.name = "m10-speaker-amp",
		.of_match_table = m10_amp_match,
	},
};
module_platform_driver(m10_amp_driver);
MODULE_DESCRIPTION("Lenovo TB-X505L speaker amplifier enable");
MODULE_LICENSE("GPL");
