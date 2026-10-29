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
#define SAMPLE_PERIOD_MS 10 /* Aim for 100 Hz telemetry; actual rate depends on ADC/I2C. */

/* Select ONLY after identifying the firmware actually installed on the motor. */
#define MOTOR_PROTOCOL_DISABLED 0
#define MOTOR_PROTOCOL_F103_SOURCE 1 /* motor ID 1..8, 1 Mbit/s */
#define MOTOR_PROTOCOL_SIMPLEFOC 2  /* letter ID, 500 kbit/s */
#ifndef MOTOR_PROTOCOL
#define MOTOR_PROTOCOL MOTOR_PROTOCOL_SIMPLEFOC
#endif
/* SimpleFOC Commander: 1 = closed-loop velocity, 3 = open-loop velocity.
 * The motor manual warns against prolonged open-loop operation. */
#ifndef MOTOR_SIMPLEFOC_VELOCITY_MODE
#define MOTOR_SIMPLEFOC_VELOCITY_MODE 1
#endif
#if MOTOR_SIMPLEFOC_VELOCITY_MODE == 3
#define MOTOR_SIMPLEFOC_VELOCITY_COMMAND "C3"
#elif MOTOR_SIMPLEFOC_VELOCITY_MODE == 1
#define MOTOR_SIMPLEFOC_VELOCITY_COMMAND "C1"
#else
#error "MOTOR_SIMPLEFOC_VELOCITY_MODE must be 1 or 3"
#endif

#define MOTOR_SOURCE_ID 1
#define MOTOR_SIMPLEFOC_ID 'M'
/* The confirmed SimpleFOC firmware uses classic CAN at 500 kbit/s. */
#define MOTOR_SIMPLEFOC_CAN_BITRATE 500000U
/* 1: send an eight-byte, zero-padded frame; 0: use the text length as DLC. */
#ifndef MOTOR_SIMPLEFOC_CAN_PAD_TO_8
#define MOTOR_SIMPLEFOC_CAN_PAD_TO_8 1
#endif
#define MOTOR_MAX_MV 300
#define MOTOR_MAX_SPEED_MRAD_S 10000
#define MOTOR_FEEDBACK_TIMEOUT_MS 300
#define MOTOR_COMMAND_TIMEOUT_MS 300

/* Standalone CAN rotation: start once after feedback and continue until fault. */
#ifndef MOTOR_AUTORUN_ENABLED
#define MOTOR_AUTORUN_ENABLED 0
#endif
#define MOTOR_AUTORUN_SPEED_MRAD_S 4000 /* 4.0 rad/s; sign sets direction */
#define MOTOR_AUTORUN_START_DELAY_MS 1500 /* Delay after XIAO startup in milliseconds. */
#define MOTOR_AUTORUN_FEEDBACK_WAIT_MS 10000
#define MOTOR_AUTORUN_HEARTBEAT_MS 100
/* Standalone mode does not require or depend on the USB console or ADC reads. */
#define MOTOR_AUTORUN_USB_DIAGNOSTICS 1
#define MOTOR_CAN_COMMAND_GAP_MS 20

/* Only change this if the motor's CAN parser is confirmed to require LF. */
#ifndef MOTOR_SIMPLEFOC_CAN_APPEND_LF
#define MOTOR_SIMPLEFOC_CAN_APPEND_LF 0
#endif

#if MOTOR_SIMPLEFOC_CAN_APPEND_LF != 0 && MOTOR_SIMPLEFOC_CAN_APPEND_LF != 1
#error "MOTOR_SIMPLEFOC_CAN_APPEND_LF must be 0 or 1"
#endif

#if MOTOR_AUTORUN_ENABLED && MOTOR_PROTOCOL != MOTOR_PROTOCOL_SIMPLEFOC
#error "Standalone speed autorun requires the SimpleFOC CAN protocol"
#endif
#if MOTOR_AUTORUN_ENABLED && (MOTOR_AUTORUN_SPEED_MRAD_S == 0 || MOTOR_AUTORUN_SPEED_MRAD_S > MOTOR_MAX_SPEED_MRAD_S || MOTOR_AUTORUN_SPEED_MRAD_S < -MOTOR_MAX_SPEED_MRAD_S)
#error "Standalone speed must be nonzero and within MOTOR_MAX_SPEED_MRAD_S"
#endif
