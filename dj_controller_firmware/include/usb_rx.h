#pragma once
#include <stdbool.h>
#include <zephyr/device.h>

#define USB_COMMAND_MAX 40

/* CDC-ACM RX is interrupt-driven; complete lines are consumed by the main loop. */
int usb_rx_init(const struct device *device);
bool usb_rx_get(char line[USB_COMMAND_MAX]);
