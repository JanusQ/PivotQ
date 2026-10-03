"""Versioned encoding-only angle floor; no changes to trainable rotations."""
import math

ENCODING_MIN_ABS_ANGLE = 0.1


def enforce_encoding_floor(angle, minimum=ENCODING_MIN_ABS_ANGLE):
    """Keep sign and large angles; map either signed zero to +minimum.

    This hard floor intentionally sacrifices smooth shutdown and is constant
    within each small-angle half-interval. Inactive modules are skipped by the
    caller before applying this function.
    """
    if not math.isfinite(angle) or not math.isfinite(minimum) or minimum <= 0:
        raise ValueError('Expected finite angle and positive finite floor')
    if abs(angle) >= minimum:
        return angle
    return -minimum if angle < 0 else minimum
