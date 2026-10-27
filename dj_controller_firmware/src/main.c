#include "adc_inputs.h"
#include "config.h"
#include "motor.h"
#include <stdint.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

static const struct device *const console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

/* CDC line protocol: MONITOR, ARM, STOP, SPEED <mrad/s>, or VQ <mV>. */
static void poll_commands(void)
{
    static char line[40];
    static size_t length;
    static bool overflow;
    unsigned char c;
    if (!device_is_ready(console)) return;
    while (uart_poll_in(console, &c) == 0) {
        if (c == '\n') {
            line[length] = 0;
            if (!overflow) motor_command(line);
            length = 0; overflow = false;
        } else if (c != '\r') {
            if (length + 1 < sizeof(line)) line[length++] = c;
            else overflow = true;
        }
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
    motor_init();
    while (1) {
        int64_t now = k_uptime_get();
        poll_commands();
        if (now >= next_motor) { motor_tick(); next_motor = now + 50; }
        if (now >= next_sample) {
            adc_inputs_sample(values);
            publish(values);
            next_sample = now + SAMPLE_PERIOD_MS;
        }
        k_sleep(K_MSEC(2));
    }
    return 0;
}
