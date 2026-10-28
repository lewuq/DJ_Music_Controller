"""User-adjustable motor feedback settings for scratch playback."""

# Positive motor speed in rad/s that produces 1x forward audio in scratch mode.
SCRATCH_REFERENCE_SPEED_RAD_S = 4.0

# Longer smoothing reduces pitch flutter from noisy CAN speed feedback, at the cost of responsiveness.
SCRATCH_RATE_SMOOTHING_SECONDS = 0.10
