#include "adc_inputs.h"
#include "config.h"
#include "motor.h"
#include "motor_autorun.h"
#include "usb_rx.h"
#include <stdint.h>
#include <string.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

static const struct device *const console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

/* CDC: existing commands plus direct SimpleFOC commands such as MC1. */
static void poll_commands(void)
{
    char line[USB_COMMAND_MAX];
    /* Bound the work so serial bursts cannot starve sampling or the watchdog. */
    for (int count = 0; count < 8 && usb_rx_get(line); ++count) {
        if (!strcmp(line, "PING")) {
            /* A non-motor diagnostic for verifying both USB directions. */
            printk("{\"v\":1,\"type\":\"pong\"}\n");
            continue;
        }
        if (!strcmp(line, "STOP") || !strcmp(line, "ME0")) motor_autorun_cancel();
        int result = motor_command(line);
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
        if (line[0] == MOTOR_SIMPLEFOC_ID && strcmp(line, "MONITOR")) {
            /* CAN ACK means transmission, not motor-side execution. */
            printk("{\"v\":1,\"type\":\"can_result\",\"id\":%d,\"error\":%d}\n",
                   MOTOR_SIMPLEFOC_ID, result);
        }
#endif
        (void)result;
    }
}

static void publish(const int32_t values[8])
{
    struct motor_status m = motor_get_status();
    /* NDJSON keeps the firmware decoupled from GUI and audio implementation. */
    printk("{\"v\":1,\"t\":%lu,\"adc_uv\":[", (unsigned long)k_uptime_get_32());
    for (int i = 0; i < 8; ++i) {
        if (i) printk(",");
        if (values[i] == INT32_MIN) printk("null");
        else printk("%ld", (long)values[i]);
    }
    printk("],\"motor\":{\"online\":%s,\"armed\":%s,\"angle_mrad\":%ld,\"rpm10\":%ld,\"error\":%d}}\n",
           m.online ? "true" : "false", m.armed ? "true" : "false",
           (long)m.angle_mrad, (long)m.rpm_tenths, m.error);
}

int main(void)
{
    int32_t values[8];
    int64_t next_sample = 0, next_motor = 0;
    int rx_error = usb_rx_init(console);
    if (rx_error) printk("USB command RX init failed: %d\n", rx_error);
    motor_init();
    motor_autorun_init();
    while (1) {
        int64_t now = k_uptime_get();
        /* CAN can run from power alone. Optional USB diagnostics keep the old UI. */
        if (!MOTOR_AUTORUN_ENABLED || MOTOR_AUTORUN_USB_DIAGNOSTICS) poll_commands();
        motor_autorun_tick();
        if (now >= next_motor) { motor_tick(); next_motor = now + 50; }
        if ((!MOTOR_AUTORUN_ENABLED || MOTOR_AUTORUN_USB_DIAGNOSTICS) && now >= next_sample) {
            adc_inputs_sample(values);
            publish(values);
            next_sample = now + SAMPLE_PERIOD_MS;
        }
        k_sleep(K_MSEC(2));
    }
    return 0;
}
