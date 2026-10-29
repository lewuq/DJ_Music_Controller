"""DJ prototype settings; times are seconds unless stated otherwise."""
SAMPLE_RATE = 48000
AUDIO_BLOCK_SIZE = 256
# F1..F5 correspond to M1 A1/A2/A3 and M2 A0/A1.
SLIDER_INDICES = (1, 2, 3, 4, 5)
SLIDER_INVERTED = (True, True, True, True, True)
SLIDER_CALIBRATION_UV = ((0, 3300000),) * 5
PICKUP_TOLERANCE = 0.035
CROSSFADE_CUT_IN = 0.04
GAIN_RAMP_SECONDS = 0.001
PLATTER_REFERENCE_RAD_S = 4.0
MOTOR_TARGET_MRAD_S = 4000
MOTOR_HEARTBEAT_SECONDS = 0.10
MOTOR_FEEDBACK_TIMEOUT_SECONDS = 0.30
JOG_STALE_SECONDS = 0.25
JOG_MAX_RAD_S = 50.0
SCRATCH_FOLLOW_SECONDS = 0.07
SCRATCH_SPEED_LIMIT = 4.0
PITCH_BEND_LIMIT = 0.15
FILTER_JOG_PER_TURN = 0.15
# Detect the end of manual rotation; no physical touch sensor is used.
SCRATCH_IDLE_SECONDS = 0.22
JOG_MIN_DELTA_RAD = 0.012

# Motorized scratch is inferred from speed deviation, not touch sensing.
MOTORIZED_WINDOW_SECONDS = 0.15
MOTORIZED_START_DEVIATION_RAD_S = 2.2
MOTORIZED_STABLE_DEVIATION_RAD_S = 1.4
MOTORIZED_ACTIVATE_SECONDS = 0.16
MOTORIZED_RELEASE_SECONDS = 0.24


# Limit forward audio speed to F4 during recovery from slowing/holding the platter.
MOTORIZED_LIMIT_RECOVERY_TO_TEMPO = True

# Short speed averaging window for responsive motorized scratching (seconds).
MOTORIZED_RATE_WINDOW_SECONDS = 0.10
