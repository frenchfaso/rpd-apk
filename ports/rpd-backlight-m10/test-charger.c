/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "m10_charger_transaction.h"

static unsigned char bus[2];
static int reads, writes, fail_read, fail_write, mask_sign;
static int fake_read(unsigned char *value)
{
	if (++reads == fail_read)
		return -EIO;
	memcpy(value, bus, 2);
	return 0;
}
static int fake_write(const unsigned char *value)
{
	bus[0] = value[0] & (mask_sign ? 0x7f : 0xff);
	/* Simulate a partially completed write on failure. */
	if (++writes == fail_write)
		return -EIO;
	bus[1] = value[1];
	return 0;
}
static struct charger_transaction reset(void)
{
	reads = writes = fail_read = fail_write = mask_sign = 0;
	bus[0] = 0x7b;
	bus[1] = 0xa4;
	return (struct charger_transaction){ .read = fake_read, .write = fake_write,
		.baseline = {0x7b, 0xa4}, .target = {0xfb, 0xa6} };
}
static void original(void)
{
	assert(bus[0] == 0x7b && bus[1] == 0xa4);
}
int main(void)
{
	struct charger_transaction t = reset();
	assert(charger_apply(&t) == 0 && t.dirty);
	assert(bus[0] == 0xfb && bus[1] == 0xa6);
	assert(charger_apply(&t) == -EBUSY);
	assert(charger_restore(&t) == 0 && !t.dirty);
	original();
	assert(charger_restore(&t) == 0 && writes == 2);
	/* Changed baseline and initial read error must not write. */
	t = reset(); bus[1] = 0xa5;
	assert(charger_apply(&t) == -EINVAL && writes == 0 && !t.dirty);
	t = reset(); fail_read = 1;
	assert(charger_apply(&t) == -EIO && writes == 0 && !t.dirty);
	/* Partial application, failed readback, and masked sign each roll back. */
	t = reset(); fail_write = 1;
	assert(charger_apply(&t) == -EIO && t.dirty);
	assert(charger_restore(&t) == 0 && !t.dirty); original();
	t = reset(); fail_read = 2;
	assert(charger_apply(&t) == -EIO && t.dirty);
	assert(charger_restore(&t) == 0 && !t.dirty); original();
	t = reset(); mask_sign = 1;
	assert(charger_apply(&t) == -EIO && t.dirty);
	assert(t.observed[0] == 0x7b && t.observed[1] == 0xa6);
	assert(charger_restore(&t) == 0 && !t.dirty); original();
	/* A rollback bus error or readback error keeps dirty set for retries. */
	t = reset(); assert(charger_apply(&t) == 0); fail_write = 2;
	assert(charger_restore(&t) == -EIO && t.dirty);
	assert(charger_restore(&t) == 0 && !t.dirty); original();
	t = reset(); assert(charger_apply(&t) == 0); fail_read = 3;
	assert(charger_restore(&t) == -EIO && t.dirty);
	assert(charger_restore(&t) == 0 && !t.dirty); original();
	/* Preconfigured OEM state is idempotent and must not be restored away. */
	t = reset(); bus[0] = 0xfb; bus[1] = 0xa6;
	assert(charger_apply(&t) == 0 && !t.dirty && writes == 0);
	assert(charger_restore(&t) == 0 && writes == 0);
	/* A new owner's value is preserved, with an explicit ownership warning. */
	t = reset(); assert(charger_apply(&t) == 0); bus[1] = 0xa7;
	assert(charger_restore(&t) == -ESTALE && !t.dirty && writes == 1);
	assert(bus[0] == 0xfb && bus[1] == 0xa7);
	/* Another actor restoring our original value needs no redundant write. */
	t = reset(); assert(charger_apply(&t) == 0); bus[0] = 0x7b; bus[1] = 0xa4;
	assert(charger_restore(&t) == 0 && !t.dirty && writes == 1);
	/* The same transaction engine also handles the exact ATL warm threshold. */
	t = reset(); bus[0] = 0x1b; bus[1] = 0xff;
	t.baseline[0] = 0x1b; t.baseline[1] = 0xff;
	t.target[0] = 0x0f; t.target[1] = 0xb3;
	assert(charger_apply(&t) == 0 && t.dirty);
	assert(bus[0] == 0x0f && bus[1] == 0xb3);
	assert(charger_restore(&t) == 0 && !t.dirty);
	assert(bus[0] == 0x1b && bus[1] == 0xff);
	puts("PASS: exact OEM bytes, baseline refusal, partial-write/readback/masked-sign failures and verified rollback retries");
	return 0;
}
