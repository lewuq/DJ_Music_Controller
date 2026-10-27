#pragma once
#include <stdbool.h>
#include <stdint.h>
struct motor_status { bool online; bool armed; int32_t angle_mrad; int32_t rpm_tenths; int error; };
void motor_init(void);
void motor_tick(void);
void motor_command(const char *line);
struct motor_status motor_get_status(void);
