#include "motor.h"
#include "config.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/can.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/printk.h>

#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_F103_SOURCE && (MOTOR_SOURCE_ID < 1 || MOTOR_SOURCE_ID > 8)
#error MOTOR_SOURCE_ID must be 1..8
#endif
static const struct device *const canbus = DEVICE_DT_GET(DT_NODELABEL(fdcan2));
static struct k_spinlock lock;
static int32_t angle_mrad, rpm_tenths;
static int64_t feedback_time = -100000;
static int64_t command_time;
static bool armed;
static bool can_started;
static int target_mv, last_error;
K_SEM_DEFINE(tx_slot, 1, 1);
K_SEM_DEFINE(tx_done, 0, 1);
static int tx_result;

static void sent(const struct device *dev, int error, void *unused)
{
    ARG_UNUSED(dev); ARG_UNUSED(unused);
    tx_result = error;
    k_sem_give(&tx_done);
    k_sem_give(&tx_slot);
}

/* Cancel queued frames on communication failure; reset is required to restart. */
static int latch_can_fault(int error)
{
    if (can_started) {
        can_started = false;
        (void)can_stop(canbus);
    }
    armed = false;
    target_mv = 0;
    last_error = error;
    return error;
}

static void receive(const struct device *dev, struct can_frame *frame, void *unused)
{
    ARG_UNUSED(dev); ARG_UNUSED(unused);
    if (frame->dlc != 8 || frame->flags) return;
    int32_t a, r;
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_F103_SOURCE
    if (frame->id != 0x100 + MOTOR_SOURCE_ID) return;
    a = (int32_t)sys_get_le32(frame->data);
    r = (int16_t)sys_get_le16(frame->data + 4);
#elif MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    if (frame->id != 0x200 + MOTOR_SIMPLEFOC_ID) return;
    uint32_t velocity_bits = sys_get_le32(frame->data), angle_bits = sys_get_le32(frame->data + 4);
    float velocity, angle;
    memcpy(&velocity, &velocity_bits, 4); memcpy(&angle, &angle_bits, 4);
    if (!isfinite(velocity) || !isfinite(angle) || fabsf(angle) > 1000000 || fabsf(velocity) > 10000) return;
    a = (int32_t)(angle * 1000.0f);
    r = (int32_t)(velocity * 95.4929659f); /* rad/s -> tenths RPM */
#else
    return;
#endif
    k_spinlock_key_t key = k_spin_lock(&lock);
    angle_mrad = a; rpm_tenths = r; feedback_time = k_uptime_get();
    k_spin_unlock(&lock, key);
}

static int send_frame(uint32_t id, const uint8_t *data, uint8_t size)
{
    struct can_frame frame = {.id = id, .dlc = size, .flags = 0};
    memcpy(frame.data, data, size);
    /* With a NULL callback Zephyr may block indefinitely waiting for CAN ACK.
     * Keep at most one frame outstanding and bound the caller's wait. */
    if (!can_started) return -ENETDOWN;
    if (k_sem_take(&tx_slot, K_NO_WAIT)) return latch_can_fault(-EBUSY);
    (void)k_sem_take(&tx_done, K_NO_WAIT); /* discard a late completion */
    int err = can_send(canbus, &frame, K_NO_WAIT, sent, NULL);
    if (err) { k_sem_give(&tx_slot); return latch_can_fault(err); }
    if (k_sem_take(&tx_done, K_MSEC(30))) return latch_can_fault(-ETIMEDOUT);
    return tx_result ? latch_can_fault(tx_result) : 0;
}
static int send_text(const char *text)
{
    size_t length = strlen(text);
    if (length > 8) return -EMSGSIZE;
    /* The supplied manual specifies eight-byte command frames. */
    uint8_t data[8] = {0};
    memcpy(data, text, length);
    return send_frame(MOTOR_SIMPLEFOC_ID, data, sizeof(data));
}
static int send_voltage(int mv)
{
    if (mv < -MOTOR_MAX_MV || mv > MOTOR_MAX_MV) return -ERANGE;
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_F103_SOURCE
    uint8_t data[8] = {0};
    int index = (MOTOR_SOURCE_ID - 1) % 4;
    sys_put_le16((uint16_t)(int16_t)mv, &data[index * 2]);
    /* The protocol transmits ALL four slots: other motors in this group get 0. */
    return send_frame(MOTOR_SOURCE_ID <= 4 ? 0x100 : 0x200, data, 8);
#elif MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    char text[16];
    int magnitude = mv < 0 ? -mv : mv;
    snprintk(text, sizeof(text), "%s%d.%03d", mv < 0 ? "-" : "", magnitude / 1000, magnitude % 1000);
    return send_text(text);
#else
    ARG_UNUSED(mv); return -ENOTSUP;
#endif
}
void motor_init(void)
{
#if MOTOR_PROTOCOL != MOTOR_PROTOCOL_DISABLED
    if (!device_is_ready(canbus)) { last_error = -ENODEV; return; }
    int err = can_set_mode(canbus, CAN_MODE_NORMAL);
    if (!err) err = can_set_bitrate(canbus, MOTOR_PROTOCOL == MOTOR_PROTOCOL_F103_SOURCE ? 1000000 : 500000);
    struct can_filter filter = {
        .id = MOTOR_PROTOCOL == MOTOR_PROTOCOL_F103_SOURCE ? 0x100 + MOTOR_SOURCE_ID : 0x200 + MOTOR_SIMPLEFOC_ID,
        .mask = CAN_STD_ID_MASK, .flags = 0,
    };
    if (!err) { int n = can_add_rx_filter(canbus, receive, NULL, &filter); if (n < 0) err = n; }
    if (!err) err = can_start(canbus);
    can_started = !err;
    last_error = err;
#endif
}
struct motor_status motor_get_status(void)
{
    struct motor_status s;
    k_spinlock_key_t key = k_spin_lock(&lock);
    s.angle_mrad = angle_mrad; s.rpm_tenths = rpm_tenths;
    s.online = can_started && k_uptime_get() - feedback_time < MOTOR_FEEDBACK_TIMEOUT_MS;
    k_spin_unlock(&lock, key);
    s.armed = armed; s.error = last_error;
    return s;
}
static void stop_motor(void)
{
    int previous_error = last_error;
    int stop_error = armed ? send_voltage(0) : 0;
    last_error = previous_error ? previous_error : stop_error;
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    /* The motor itself may have started enabled even if this host never armed. */
    if (can_started) { int err = send_text("E0"); if (err) last_error = err; }
#endif
    armed = false; target_mv = 0;
}
void motor_command(const char *line)
{
    if (!strcmp(line, "STOP")) { stop_motor(); return; }
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
    /* Enable the manual's target/Vq/velocity/angle monitoring explicitly. */
    if (!strcmp(line, "MONITOR")) { last_error = can_started ? send_text("MG7") : -ENODEV; return; }
#endif
    if (!strcmp(line, "ARM")) {
        if (MOTOR_PROTOCOL == MOTOR_PROTOCOL_DISABLED || !motor_get_status().online || last_error) return;
#if MOTOR_PROTOCOL == MOTOR_PROTOCOL_SIMPLEFOC
        /* Mode switch and enable are only sent on an explicit host command. */
        last_error = send_voltage(0);
        if (!last_error) last_error = send_text("C0");
        if (!last_error) last_error = send_text("E1");
        if (last_error) { send_text("E0"); return; }
#endif
        armed = true; target_mv = 0; command_time = k_uptime_get(); return;
    }
    if (!strncmp(line, "VQ ", 3) && armed) {
        char *end;
        long value = strtol(line + 3, &end, 10);
        if (*end || end == line + 3 || value < -MOTOR_MAX_MV || value > MOTOR_MAX_MV) return;
        target_mv = (int)value; command_time = k_uptime_get();
    }
}
void motor_tick(void)
{
    if (!armed) return;
    if (!motor_get_status().online || k_uptime_get() - command_time > MOTOR_COMMAND_TIMEOUT_MS) {
        stop_motor(); return;
    }
    last_error = send_voltage(target_mv);
    if (last_error) stop_motor();
}
