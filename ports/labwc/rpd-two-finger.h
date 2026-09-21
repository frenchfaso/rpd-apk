/* SPDX-License-Identifier: GPL-2.0-only */
/* Small, dependency-free recognizer. Coordinates are compositor layout pixels. */
#ifndef RPD_TWO_FINGER_H
#define RPD_TWO_FINGER_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
enum rpd_event { RPD_DOWN, RPD_MOTION, RPD_UP };
enum rpd_result { RPD_BUFFER, RPD_FLUSH, RPD_RIGHT, RPD_PASS };
struct rpd_tap {
    unsigned active, seen;
    bool pending;
    uint32_t start;
    int32_t id[2];
    double x[2], y[2];
};
static inline enum rpd_result
rpd_tap_event(struct rpd_tap *s, enum rpd_event event, int32_t id,
        uint32_t time, double x, double y)
{
    if (event == RPD_DOWN) {
        if (!s->active) {
            memset(s, 0, sizeof(*s));
            s->pending = true;
            s->start = time;
        }
        ++s->active;
        if (s->pending) {
            if (s->seen == 2 || (s->seen && time - s->start > 150)) {
                s->pending = false;
                return RPD_FLUSH;
            }
            s->id[s->seen] = id;
            s->x[s->seen] = x;
            s->y[s->seen++] = y;
        }
    }
    if (event == RPD_UP && s->active) {
        --s->active;
    }
    if (!s->pending) {
        return RPD_PASS;
    }
    bool moved = false;
    if (event == RPD_MOTION) {
        for (unsigned i = 0; i < s->seen; ++i) {
            double dx = x - s->x[i], dy = y - s->y[i];
            if (s->id[i] == id && dx * dx + dy * dy > 144) {
                moved = true;
            }
        }
    }
    if (moved || time - s->start > 260 || !s->active) {
        s->pending = false;
        return !moved && time - s->start <= 260 && !s->active && s->seen == 2
            ? RPD_RIGHT : RPD_FLUSH;
    }
    return RPD_BUFFER;
}
#endif
