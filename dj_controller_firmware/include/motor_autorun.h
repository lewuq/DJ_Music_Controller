#pragma once

/* The startup attempt is single-shot; a failure requires a controller reset. */
void motor_autorun_init(void);
void motor_autorun_tick(void);
void motor_autorun_cancel(void);
