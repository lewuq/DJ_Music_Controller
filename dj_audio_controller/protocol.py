"""Decode versioned firmware telemetry and normalize physical slider inputs."""
import json
import math

# Firmware layout is module 1 A0..A3, followed by module 2 A0..A3.
SLIDER_INDICES = (1, 2, 3, 4, 5)

def parse_line(line):
    try:
        value = json.loads(line)
        if value.get("v") != 1 or len(value["adc_uv"]) != 8:
            return None
        if not isinstance(value.get("motor"), dict):
            return None
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        return None

def normalize(uv, low=0, high=3300000, inverted=False):
    if uv is None or isinstance(uv, bool) or not isinstance(uv, (float, int)) or not math.isfinite(uv):
        return None
    if high <= low:
        raise ValueError("Calibration maximum must exceed minimum")
    value = min(1.0, max(0.0, (uv - low) / (high - low)))
    return 1.0 - value if inverted else value
