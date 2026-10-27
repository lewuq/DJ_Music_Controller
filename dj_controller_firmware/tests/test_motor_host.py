"""Exercise the actual motor state machine with a synchronous fake CAN bus.

Run with Python 3 and a C compiler: python -m unittest discover -s tests -v.
This does not replace a Zephyr build or a hardware test.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
struct device { int unused; };
struct can_frame { uint32_t id; uint8_t dlc, flags, data[8]; };
struct can_filter { uint32_t id, mask, flags; };
struct k_spinlock { int unused; };
typedef int k_spinlock_key_t;
struct k_sem { int value; };
#define K_SEM_DEFINE(name, count, limit) struct k_sem name = {count}
#define K_NO_WAIT 0
#define K_MSEC(x) (x)
#define ARG_UNUSED(x) ((void)(x))
#define DT_NODELABEL(x) 0
#define DEVICE_DT_GET(x) (&fake_device)
#define CAN_MODE_NORMAL 0
#define CAN_STD_ID_MASK 0x7ff
#define snprintk snprintf
static struct device fake_device;
static int64_t fake_time;
static struct can_frame frames[128];
static int frame_count;
static int send_error;
static int64_t k_uptime_get(void) { return fake_time; }
static k_spinlock_key_t k_spin_lock(struct k_spinlock *x) { (void)x; return 0; }
static void k_spin_unlock(struct k_spinlock *x, int y) { (void)x; (void)y; }
static int k_sem_take(struct k_sem *s, int timeout) { (void)timeout; if (!s->value) return -1; --s->value; return 0; }
static void k_sem_give(struct k_sem *s) { s->value = 1; }
static bool device_is_ready(const struct device *d) { (void)d; return true; }
static int can_set_mode(const struct device *d, int m) { (void)d; (void)m; return 0; }
static int can_set_bitrate(const struct device *d, int n) { (void)d; (void)n; return 0; }
static int can_add_rx_filter(const struct device *d, void (*cb)(const struct device *, struct can_frame *, void *), void *u, const struct can_filter *f) { (void)d; (void)cb; (void)u; (void)f; return 0; }
static int can_start(const struct device *d) { (void)d; return 0; }
static int can_stop(const struct device *d) { (void)d; return 0; }
static int can_send(const struct device *d, struct can_frame *f, int t, void (*cb)(const struct device *, int, void *), void *u) {
    (void)t; if (send_error) return send_error;
    frames[frame_count++] = *f; cb(d, 0, u); return 0;
}
static uint32_t sys_get_le32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint16_t sys_get_le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1]<<8); }
static void sys_put_le16(uint16_t v, uint8_t *p) { p[0] = v; p[1] = v >> 8; }
'''
HARNESS = r'''
#include <assert.h>
#include "fake.h"
#include "motor.c"
static void feedback(void) {
    struct can_frame f = {0}; f.dlc = 8;
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    f.id = 0x200 + MOTOR_SIMPLEFOC_ID;
#else
    f.id = 0x100 + MOTOR_SOURCE_ID;
#endif
    receive(&fake_device, &f, NULL);
}
static void check_text(int i, const char *s) {
    assert(frames[i].id == MOTOR_SIMPLEFOC_ID && frames[i].dlc == 8);
    assert(!memcmp(frames[i].data, s, strlen(s)));
    for (size_t n = strlen(s); n < 8; ++n) assert(frames[i].data[n] == 0);
}
int main(void) {
    motor_init();
    motor_command("ARM"); assert(!motor_get_status().armed && frame_count == 0);
    feedback(); motor_command("ARM"); assert(motor_get_status().armed);
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    assert(frame_count == 3); check_text(0, "0.000"); check_text(1, "C1"); check_text(2, "E1");
    motor_command("SPEED -1234"); motor_tick(); check_text(3, "-1.234");
    motor_command("SPEED 10000"); motor_tick(); check_text(4, "10.000");
    motor_command("SPEED 10001"); motor_command("VQ 200"); motor_tick(); check_text(5, "10.000");
    motor_command("STOP"); check_text(6, "0.000"); check_text(7, "E0"); assert(!motor_get_status().armed);
    motor_command("ARM"); motor_command("SPEED 500"); fake_time = 301; feedback(); motor_tick();
    assert(!motor_get_status().armed); check_text(11, "0.000"); check_text(12, "E0");
    fake_time = 302; feedback(); motor_command("ARM"); motor_command("SPEED 500");
    fake_time = 603; motor_command("SPEED 500"); motor_tick(); /* stale feedback */
    assert(!motor_get_status().armed); check_text(16, "0.000"); check_text(17, "E0");
    fake_time = 604; feedback(); motor_command("ARM"); motor_command("SPEED 500"); send_error = -5;
    motor_tick(); assert(!motor_get_status().armed && motor_get_status().error == -5);
#else
    assert(frame_count == 0);
    motor_command("VQ -123"); motor_tick(); assert(frames[0].id == 0x100 && frames[0].data[0] == 0x85 && frames[0].data[1] == 0xff);
    motor_command("VQ 301"); motor_tick(); assert(frames[1].data[0] == 0x85 && frames[1].data[1] == 0xff);
    motor_command("STOP"); assert(frames[2].data[0] == 0 && frames[2].data[1] == 0); assert(!motor_get_status().armed);
#endif
    return 0;
}
'''


class MotorTests(unittest.TestCase):
    def test_both_protocols(self):
        compiler = shutil.which(os.environ.get("CC", "gcc"))
        if not compiler:
            self.skipTest("gcc unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            (temp / "fake.h").write_text(FAKE, encoding="utf-8")
            for header in ("device.h", "devicetree.h", "kernel.h", "drivers/can.h", "sys/byteorder.h", "sys/printk.h"):
                path = temp / "zephyr" / header
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            (temp / "test.c").write_text(HARNESS, encoding="utf-8")
            for protocol in ("MOTOR_PROTOCOL_SIMPLEFOC", "MOTOR_PROTOCOL_F103_SOURCE"):
                with self.subTest(protocol=protocol):
                    exe = temp / (protocol + ".exe")
                    subprocess.run([compiler, "-std=c11", "-DMOTOR_PROTOCOL=" + protocol,
                                    "-I", str(temp), "-I", str(ROOT / "include"),
                                    "-I", str(ROOT / "src"), str(temp / "test.c"),
                                    "-o", str(exe)], check=True)
                    subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
