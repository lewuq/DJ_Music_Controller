#include "adc_inputs.h"
#include "config.h"
#include <stdbool.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>

static const struct device *const bus = DEVICE_DT_GET(DT_NODELABEL(i2c1));
static const uint8_t addr[2] = {ADC1_ADDRESS, ADC2_ADDRESS};
static const bool enabled[2][4] = {{M1_A0,M1_A1,M1_A2,M1_A3}, {M2_A0,M2_A1,M2_A2,M2_A3}};

static int write_config(uint8_t address, uint16_t value)
{
    uint8_t data[] = {1, value >> 8, value & 0xff};
    return i2c_write(bus, data, sizeof(data), address);
}
static int read_reg(uint8_t address, uint8_t reg, uint16_t *value)
{
    uint8_t data[2];
    int err = i2c_write_read(bus, address, &reg, 1, data, sizeof(data));
    if (!err) *value = ((uint16_t)data[0] << 8) | data[1];
    return err;
}
void adc_inputs_sample(int32_t values[8])
{
    for (int i = 0; i < 8; ++i) values[i] = INT32_MIN;
    if (!device_is_ready(bus)) return;
    for (int ch = 0; ch < 4; ++ch) {
        bool started[2] = {false, false};
        for (int m = 0; m < 2; ++m) {
            /* AINx vs GND, 4.096 V FSR, single-shot, 128 SPS. */
            if (enabled[m][ch]) started[m] = !write_config(addr[m], 0xC383 | (ch << 12));
        }
        for (int m = 0; m < 2; ++m) {
            if (!started[m]) continue;
            int64_t deadline = k_uptime_get() + 50;
            uint16_t reg;
            do {
                if (read_reg(addr[m], 1, &reg)) break;
                if (reg & 0x8000) {
                    if (!read_reg(addr[m], 0, &reg)) values[m * 4 + ch] = (int16_t)reg * 125;
                    break;
                }
                k_sleep(K_MSEC(1));
            } while (k_uptime_get() < deadline);
        }
    }
}
