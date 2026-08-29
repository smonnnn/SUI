"""Helper module mixable into layouts via ``@import suifx``.

Any public (non-underscore) name here becomes available to calc(), script()
and click callbacks throughout a layout.
"""
import math

def label_for(prefix, value):
    return f"{prefix} #{value:03d}"

def glow(rgb, t):
    """Pulse a color triplet based on time (0..1)."""
    k = 0.5 + 0.5 * math.sin(t)
    return [int(c * (0.6 + 0.6 * k)) for c in rgb]

def pingpong(x, lo, hi):
    val = (x + hi) % (2 * (hi - lo))
    return lo + (val if val < hi else 2 * hi - val)
