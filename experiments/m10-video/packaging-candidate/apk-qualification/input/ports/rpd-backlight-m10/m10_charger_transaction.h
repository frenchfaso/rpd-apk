/* SPDX-License-Identifier: GPL-2.0-only */
/* Two-byte transaction, shared by the charger module and fault tests.
 * Each callback pair accesses one fixed, qualified two-byte register.
 */
struct charger_transaction {
	int (*read)(unsigned char *value);
	int (*write)(const unsigned char *value);
	unsigned char baseline[2];
	unsigned char target[2];
	unsigned char original[2];
	unsigned char observed[2];
	int dirty;
	int verified;
};

static int charger_restore(struct charger_transaction *t)
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
		if (value[0] != t->target[0] || value[1] != t->target[1]) {
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

static int charger_apply(struct charger_transaction *t)
{

	int ret;
	if (t->dirty)
		return -EBUSY;
	ret = t->read(t->original);
	if (ret)
		return ret;
	/* Already OEM-configured: observe, do not acquire write ownership. */
	if (t->original[0] == t->target[0] && t->original[1] == t->target[1]) {
		t->observed[0] = t->target[0];
		t->observed[1] = t->target[1];
		return 0;
	}
	if (t->original[0] != t->baseline[0] || t->original[1] != t->baseline[1])
		return -EINVAL;
	t->verified = 0;
	/* A failed bus write can still have modified one byte. */
	t->dirty = 1;
	ret = t->write(t->target);
	if (ret)
		return ret;
	ret = t->read(t->observed);
	if (ret)
		return ret;
	if (t->observed[0] != t->target[0] || t->observed[1] != t->target[1])
		return -EIO;
	t->verified = 1;
	return 0;
}
