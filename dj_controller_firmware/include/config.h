#pragma once

/* Set a channel to 1 to publish it; retain the current wiring. */
#define M1_A0 0
#define M1_A1 1
#define M1_A2 1
#define M1_A3 1
#define M2_A0 1
#define M2_A1 1
#define M2_A2 0
#define M2_A3 0
#define ADC1_ADDRESS 0x49
#define ADC2_ADDRESS 0x48
#define SAMPLE_PERIOD_MS 50

/* Select ONLY after identifying the firmware actually installed on the motor. */
#define MOTOR_PROTOCOL_DISABLED 0
#define MOTOR_PROTOCOL_F103_SOURCE 1 /* motor ID 1..8, 1 Mbit/s */
#define MOTOR_PROTOCOL_SIMPLEFOC 2  /* letter ID, 500 kbit/s */
#ifndef MOTOR_PROTOCOL
#define MOTOR_PROTOCOL MOTOR_PROTOCOL_SIMPLEFOC
#endif
#define MOTOR_SOURCE_ID 1
#define MOTOR_SIMPLEFOC_ID 'M'
#define MOTOR_MAX_MV 300
#define MOTOR_FEEDBACK_TIMEOUT_MS 300
#define MOTOR_COMMAND_TIMEOUT_MS 300
