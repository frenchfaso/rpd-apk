/* SPDX-License-Identifier: GPL-2.0-only */
#include "rpd-two-finger.h"
#include <assert.h>
#include <stdio.h>
#define E(kind,id,time,x,y) rpd_tap_event(&s, RPD_##kind,id,time,x,y)
int main(void) {
    struct rpd_tap s = {0};
    assert(E(DOWN,1,0,100,100)==RPD_BUFFER);
    assert(E(UP,1,70,0,0)==RPD_FLUSH); /* native single tap */
    for (int reverse=0;reverse<2;reverse++) {
        assert(E(DOWN,1,1000,100,100)==RPD_BUFFER);
        assert(E(DOWN,2,1050,130,100)==RPD_BUFFER);
        assert(E(UP,reverse?1:2,1100,0,0)==RPD_BUFFER);
        assert(E(UP,reverse?2:1,1150,0,0)==RPD_RIGHT);
    }
    assert(E(DOWN,1,2000,100,100)==RPD_BUFFER);
    assert(E(MOTION,1,2010,113,100)==RPD_FLUSH); /* drag */
    assert(E(UP,1,2020,0,0)==RPD_PASS);
    assert(E(DOWN,1,3000,100,100)==RPD_BUFFER);
    assert(E(DOWN,2,3010,130,100)==RPD_BUFFER);
    assert(E(MOTION,2,3020,150,100)==RPD_FLUSH); /* pinch/scroll */
    assert(E(UP,1,3030,0,0)==RPD_PASS);
    assert(E(UP,2,3040,0,0)==RPD_PASS);
    assert(E(DOWN,1,4000,100,100)==RPD_BUFFER);
    assert(E(DOWN,2,4010,130,100)==RPD_BUFFER);
    assert(E(DOWN,3,4020,150,100)==RPD_FLUSH);
    assert(E(UP,1,4030,0,0)==RPD_PASS);
    assert(E(UP,2,4040,0,0)==RPD_PASS);
    assert(E(UP,3,4050,0,0)==RPD_PASS);
    assert(E(DOWN,1,5000,100,100)==RPD_BUFFER);
    assert(E(DOWN,2,5170,130,100)==RPD_FLUSH); /* staggered, not a chord */
    assert(E(UP,1,5200,0,0)==RPD_PASS);
    assert(E(UP,2,5210,0,0)==RPD_PASS);
    assert(E(DOWN,1,6000,100,100)==RPD_BUFFER);
    assert(E(DOWN,2,6050,130,100)==RPD_BUFFER);
    assert(E(UP,1,6280,0,0)==RPD_FLUSH); /* hold */
    assert(E(UP,2,6290,0,0)==RPD_PASS);
    assert(E(DOWN,1,UINT32_MAX-50,100,100)==RPD_BUFFER);
    assert(E(DOWN,2,UINT32_MAX-20,130,100)==RPD_BUFFER);
    assert(E(UP,1,20,0,0)==RPD_BUFFER);
    assert(E(UP,2,40,0,0)==RPD_RIGHT); /* millisecond timestamp wrap */
    assert(E(DOWN,1,7000,100,100)==RPD_BUFFER);
    s.pending=false; /* timer expiry / queue overflow flush */
    assert(E(DOWN,2,7100,130,100)==RPD_PASS);
    assert(E(UP,1,7110,0,0)==RPD_PASS);
    assert(E(UP,2,7120,0,0)==RPD_PASS);
    assert(E(DOWN,1,8000,100,100)==RPD_BUFFER); /* recovers after passthrough */
    assert(E(UP,1,8030,0,0)==RPD_FLUSH);
    puts("Two-finger recognizer: native tap, right tap, drag, pinch, third finger, timing and wrap passed");
}
