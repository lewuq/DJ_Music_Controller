#include "usb_rx.h"
#include <errno.h>
#include <string.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>

/* Message queue transfers complete commands from the UART callback to main. */
K_MSGQ_DEFINE(command_queue, USB_COMMAND_MAX, 8, 4);
static char rx_line[USB_COMMAND_MAX];
static size_t rx_length;
static bool rx_overflow;

static void accept_byte(unsigned char c)
{
    if (c == '\r') return;
    if (c != '\n') {
        if (rx_length + 1 < sizeof(rx_line)) rx_line[rx_length++] = (char)c;
        else rx_overflow = true;
        return;
    }
    if (!rx_overflow && rx_length > 0) {
        rx_line[rx_length] = '\0';
        /* Drop older queued commands before an explicit stop. An already
         * executing CAN command cannot be cancelled by this queue. */
        if (!strcmp(rx_line, "STOP") || !strcmp(rx_line, "ME0"))
            k_msgq_purge(&command_queue);
        (void)k_msgq_put(&command_queue, rx_line, K_NO_WAIT);
    }
    rx_length = 0;
    rx_overflow = false;
}

static void rx_callback(const struct device *dev, void *user_data)
{
    unsigned char bytes[32];
    (void)user_data;
    while (uart_irq_update(dev) && uart_irq_rx_ready(dev)) {
        int count = uart_fifo_read(dev, bytes, sizeof(bytes));
        if (count <= 0) break;
        for (int i = 0; i < count; ++i) accept_byte(bytes[i]);
    }
}

int usb_rx_init(const struct device *device)
{
    if (!device_is_ready(device)) return -ENODEV;
    int err = uart_irq_callback_user_data_set(device, rx_callback, NULL);
    if (err) return err;
    /* CDC-ACM does not post its first OUT request until RX is enabled. */
    uart_irq_rx_enable(device);
    return 0;
}

bool usb_rx_get(char line[USB_COMMAND_MAX])
{
    return k_msgq_get(&command_queue, line, K_NO_WAIT) == 0;
}
