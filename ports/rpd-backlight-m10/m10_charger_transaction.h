/* SPDX-License-Identifier: GPL-2.0-only */
/* Two-byte transaction, shared by the charger module and fault tests.
 * The callbacks can access only CHGR_ADC_ITERM_UP_THD_MSB/LSB.
 */
struct term_transaction {
	int (*read)(unsigned char *value);
	int (*write)(const unsigned char *value);
	unsigned char original[2];
	unsigned char observed[2];
	int dirty;
	int verified;
};

static int term_restore(struct term_transaction *t)
{
	unsigned char value[2];
	int ret;
	if (!t->dirty)
		return 0;
	/* Do not overwrite a different driver's setting during teardown. */
	if (t->verified) {
		ret = t->read(value);
		if (ret)
			return ret;
		if (value[0] == t->original[0] && value[1] == t->original[1]) {
			t->dirty = 0;
			return 0;
		}
		if (value[0] != 0xfb || value[1] != 0xa6) {
			t->dirty = 0;
			return -ESTALE;
		}
	}
	/* A partial rollback is still ours, not a new external owner's value. */
	t->verified = 0;
	ret = t->write(t->original);
	if (ret)
		return ret;
	ret = t->read(value);
	if (ret)
		return ret;
	if (value[0] != t->original[0] || value[1] != t->original[1])
		return -EIO;
	t->dirty = 0;
	return 0;
}

static int term_apply(struct term_transaction *t)
{
	/* Exact signed Lenovo PMI632 conversion, C division truncates to zero. */
	int raw = -170 * 10000 / 1525;
	unsigned int word = (unsigned int)raw & 0xffff;
	unsigned char target[2] = { word >> 8, word & 0xff };
	int ret;
	if (t->dirty)
		return -EBUSY;
	ret = t->read(t->original);
	if (ret)
		return ret;
	/* Already OEM-configured: observe, do not acquire write ownership. */
	if (t->original[0] == target[0] && t->original[1] == target[1]) {
		t->observed[0] = target[0];
		t->observed[1] = target[1];
		return 0;
	}
	if (t->original[0] != 0x7b || t->original[1] != 0xa4)
		return -EINVAL;
	t->verified = 0;
	/* A failed bus write can still have modified one byte. */
	t->dirty = 1;
	ret = t->write(target);
	if (ret)
		return ret;
	ret = t->read(t->observed);
	if (ret)
		return ret;
	if (t->observed[0] != target[0] || t->observed[1] != target[1])
		return -EIO;
	t->verified = 1;
	return 0;
}
