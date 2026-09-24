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
static struct term_transaction reset(void)
{
	reads = writes = fail_read = fail_write = mask_sign = 0;
	bus[0] = 0x7b;
	bus[1] = 0xa4;
	return (struct term_transaction){ .read = fake_read, .write = fake_write };
}
static void original(void)
{
	assert(bus[0] == 0x7b && bus[1] == 0xa4);
}
int main(void)
{
	struct term_transaction t = reset();
	assert(term_apply(&t) == 0 && t.dirty);
	assert(bus[0] == 0xfb && bus[1] == 0xa6);
	assert(term_apply(&t) == -EBUSY);
	assert(term_restore(&t) == 0 && !t.dirty);
	original();
	assert(term_restore(&t) == 0 && writes == 2);
	/* Changed baseline and initial read error must not write. */
	t = reset(); bus[1] = 0xa5;
	assert(term_apply(&t) == -EINVAL && writes == 0 && !t.dirty);
	t = reset(); fail_read = 1;
	assert(term_apply(&t) == -EIO && writes == 0 && !t.dirty);
	/* Partial application, failed readback, and masked sign each roll back. */
	t = reset(); fail_write = 1;
	assert(term_apply(&t) == -EIO && t.dirty);
	assert(term_restore(&t) == 0 && !t.dirty); original();
	t = reset(); fail_read = 2;
	assert(term_apply(&t) == -EIO && t.dirty);
	assert(term_restore(&t) == 0 && !t.dirty); original();
	t = reset(); mask_sign = 1;
	assert(term_apply(&t) == -EIO && t.dirty);
	assert(t.observed[0] == 0x7b && t.observed[1] == 0xa6);
	assert(term_restore(&t) == 0 && !t.dirty); original();
	/* A rollback bus error or readback error keeps dirty set for retries. */
	t = reset(); assert(term_apply(&t) == 0); fail_write = 2;
	assert(term_restore(&t) == -EIO && t.dirty);
	assert(term_restore(&t) == 0 && !t.dirty); original();
	t = reset(); assert(term_apply(&t) == 0); fail_read = 3;
	assert(term_restore(&t) == -EIO && t.dirty);
	assert(term_restore(&t) == 0 && !t.dirty); original();
	/* Preconfigured OEM state is idempotent and must not be restored away. */
	t = reset(); bus[0] = 0xfb; bus[1] = 0xa6;
	assert(term_apply(&t) == 0 && !t.dirty && writes == 0);
	assert(term_restore(&t) == 0 && writes == 0);
	/* A new owner's value is preserved, with an explicit ownership warning. */
	t = reset(); assert(term_apply(&t) == 0); bus[1] = 0xa7;
	assert(term_restore(&t) == -ESTALE && !t.dirty && writes == 1);
	assert(bus[0] == 0xfb && bus[1] == 0xa7);
	/* Another actor restoring our original value needs no redundant write. */
	t = reset(); assert(term_apply(&t) == 0); bus[0] = 0x7b; bus[1] = 0xa4;
	assert(term_restore(&t) == 0 && !t.dirty && writes == 1);
	puts("PASS: exact OEM bytes, baseline refusal, partial-write/readback/masked-sign failures and verified rollback retries");
	return 0;
}
