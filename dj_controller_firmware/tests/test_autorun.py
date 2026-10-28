"""Verify autonomous startup, sustained heartbeat and fault latching with fake CAN."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_motor_host import FAKE

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <assert.h>
#include "fake.h"
#include "motor.c"
#include "motor_autorun.c"
static void feedback(void) {
    struct can_frame f = {0}; f.dlc = 8; f.id = 0x200 + MOTOR_SIMPLEFOC_ID;
    receive(&fake_device, &f, NULL);
}
static void text_at(int i, const char *s) {
    assert(frames[i].id == MOTOR_SIMPLEFOC_ID);
    assert(!memcmp(frames[i].data, s, strlen(s)));
}
int main(void) {
    motor_init(); motor_autorun_init(); motor_autorun_tick();
    assert(frame_count == 0 && !motor_get_status().armed);
    fake_time = MOTOR_AUTORUN_START_DELAY_MS - 1; feedback(); motor_autorun_tick();
    assert(frame_count == 0 && !motor_get_status().armed);
    fake_time = MOTOR_AUTORUN_START_DELAY_MS; motor_autorun_tick();
    assert(motor_get_status().armed && frame_count == 3);
    text_at(0, "0.000"); text_at(1, "C1"); text_at(2, "E1");
    motor_tick(); text_at(3, "4.000");
    for (int i = 1; i <= 120; ++i) {
        fake_time = MOTOR_AUTORUN_START_DELAY_MS + i * 100;
        feedback(); motor_autorun_tick(); motor_tick();
        assert(motor_get_status().armed);
    }
    /* After more than 10 seconds it still runs, then stale feedback halts it. */
    assert(fake_time == MOTOR_AUTORUN_START_DELAY_MS + 12000 && frame_count == 124);
    fake_time += MOTOR_FEEDBACK_TIMEOUT_MS + 1;
    motor_autorun_tick();
    assert(!motor_get_status().armed && frame_count == 126);
    text_at(124, "0.000"); text_at(125, "E0");
    feedback(); fake_time += 1000; motor_autorun_tick();
    assert(!motor_get_status().armed && frame_count == 126);
    /* Startup without feedback times out and does not start later. */
    motor_autorun_init();
    fake_time += MOTOR_AUTORUN_START_DELAY_MS + MOTOR_AUTORUN_FEEDBACK_WAIT_MS;
    motor_autorun_tick(); feedback(); motor_autorun_tick();
    assert(!motor_get_status().armed && frame_count == 126);
    /* A CAN transmit failure latches the controller and prevents restart. */
    motor_autorun_init(); fake_time += MOTOR_AUTORUN_START_DELAY_MS;
    feedback(); send_error = -5; motor_autorun_tick();
    assert(!motor_get_status().armed && motor_get_status().error == -5);
    send_error = 0; feedback(); motor_autorun_tick();
    assert(!motor_get_status().armed && frame_count == 126);
    return 0;
}
'''

class AutorunTests(unittest.TestCase):
    def test_start_sustain_stop_and_no_restart(self):
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
            exe = temp / "autorun.exe"
            subprocess.run([compiler, "-std=c11", "-DMOTOR_AUTORUN_ENABLED=1", "-I", str(temp), "-I", str(ROOT / "include"),
                            "-I", str(ROOT / "src"), str(temp / "test.c"), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

if __name__ == "__main__":
    unittest.main()
