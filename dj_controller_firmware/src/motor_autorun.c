#include "motor_autorun.h"
#include "config.h"
#include "motor.h"
#include <stdbool.h>
#include <stdint.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

enum autorun_state { WAITING, RUNNING, HALTED };
static enum autorun_state state;
static int64_t start_time, last_heartbeat;

void motor_autorun_init(void)
{
    start_time = k_uptime_get();
    state = WAITING;
}

void motor_autorun_cancel(void)
{
    /* The caller sends STOP; do not restart automatically afterward. */
    state = HALTED;
}

void motor_autorun_tick(void)
{
#if MOTOR_AUTORUN_ENABLED
    int64_t now = k_uptime_get();
    struct motor_status status = motor_get_status();
    if (state == HALTED) return;
    if (status.error) {
        if (status.armed) (void)motor_command("STOP");
        state = HALTED;
        return;
    }

    if (state == WAITING) {
        if (now - start_time < MOTOR_AUTORUN_START_DELAY_MS) return;
        if (!status.online) {
            if (now - start_time >= MOTOR_AUTORUN_START_DELAY_MS + MOTOR_AUTORUN_FEEDBACK_WAIT_MS)
                state = HALTED;
            return;
        }
        /* ARM sends zero, the configured velocity mode and E1. Feedback is required first. */
        if (motor_command("ARM")) { state = HALTED; return; }
        state = RUNNING;
        last_heartbeat = now - MOTOR_AUTORUN_HEARTBEAT_MS;
    }

    if (state == RUNNING) {
        status = motor_get_status();
        if (!status.online || !status.armed || status.error) {
            if (status.armed) (void)motor_command("STOP");
            state = HALTED;
            return;
        }
        if (now - last_heartbeat >= MOTOR_AUTORUN_HEARTBEAT_MS) {
            char cmd[32];
            snprintk(cmd, sizeof(cmd), "SPEED %d", MOTOR_AUTORUN_SPEED_MRAD_S);
            if (motor_command(cmd)) {
                (void)motor_command("STOP");
                state = HALTED;
                return;
            }
            last_heartbeat = now;
        }
    }
#endif
}
