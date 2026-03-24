"""
Parameterized pseudo-log encoding for inverse LUT baking (JPlog2-style).

Based on jplog2_tk2.pdf: piecewise linear toe + log2 section in normalized [0,1],
giving more highlight headroom than ACEScc-style pure log in the same cube domain.

lin_to_pseudolog / pseudolog_to_lin are exact inverses (when in range).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class PseudoLogParams:
    """Defaults match JPlog2 from jplog2_tk2.pdf (Table / C routines)."""

    lin_break: float = 0.00680  # linear / log boundary (linear light)
    log_break_norm: float = 165.0 / 1023.0  # normalized code at break (~0.16129)
    lin_slope: float = 10.367739  # lintolog slope (norm per unit linear)
    lin_yint: float = 0.0907775  # lintolog y-intercept (norm)
    log_divisor: float = 20.46  # norm = (log2(lin) + log_offset) / log_divisor
    log_offset: float = 10.5

    def validate(self) -> None:
        if self.lin_break <= 0:
            raise ValueError("lin_break must be > 0")
        if self.log_divisor <= 0:
            raise ValueError("log_divisor must be > 0")


def lin_to_pseudolog(lin: np.ndarray, p: PseudoLogParams) -> np.ndarray:
    """AP1 linear -> normalized pseudo-log [0, 1]."""
    p.validate()
    x = np.asarray(lin, dtype=np.float64)
    out = np.empty_like(x, dtype=np.float64)
    mask = x <= p.lin_break
    out[mask] = p.lin_slope * x[mask] + p.lin_yint
    safe = np.maximum(x[~mask], np.finfo(np.float64).tiny)
    out[~mask] = (np.log2(safe) + p.log_offset) / p.log_divisor
    return np.clip(out, 0.0, 1.0)


def pseudolog_to_lin(norm: np.ndarray, p: PseudoLogParams) -> np.ndarray:
    """Normalized pseudo-log [0, 1] -> AP1 linear."""
    p.validate()
    y = np.asarray(norm, dtype=np.float64)
    out = np.empty_like(y, dtype=np.float64)
    mask = y <= p.log_break_norm
    out[mask] = (y[mask] - p.lin_yint) / p.lin_slope
    out[~mask] = np.power(2.0, y[~mask] * p.log_divisor - p.log_offset)
    return out


def build_decode_lut1d(length: int, p: PseudoLogParams) -> "object":
    """OCIO Lut1D: input normalized [0,1] -> output linear AP1 (same on RGB)."""
    import PyOpenColorIO as ocio

    n = max(int(length), 2)
    n1 = n - 1
    lut = ocio.Lut1DTransform(length=n)
    for i in range(n):
        t = i / n1
        lin = float(pseudolog_to_lin(np.array([t]), p)[0])
        lut.setValue(i, lin, lin, lin)
    return lut


def build_encode_lut1d(
    length: int, p: PseudoLogParams, lin_min: float, lin_max: float
) -> Tuple["object", float, float]:
    """
    OCIO Lut1D: input t in [0,1] (after Range maps [lin_min, lin_max] -> [0,1])
    -> output normalized pseudo-log [0,1].
    """
    import PyOpenColorIO as ocio

    if lin_max <= lin_min:
        raise ValueError("lin_max must be > lin_min")
    n = max(int(length), 2)
    n1 = n - 1
    lut = ocio.Lut1DTransform(length=n)
    for i in range(n):
        t = i / n1
        lin = lin_min + t * (lin_max - lin_min)
        jp = float(lin_to_pseudolog(np.array([lin]), p)[0])
        lut.setValue(i, jp, jp, jp)
    return lut, lin_min, lin_max


def make_range_lin_to_unit(lin_min: float, lin_max: float):
    """Range: AP1 linear [lin_min, lin_max] -> [0, 1] (clamped)."""
    import PyOpenColorIO as ocio

    r = ocio.RangeTransform()
    r.setMinInValue(float(lin_min))
    r.setMaxInValue(float(lin_max))
    r.setMinOutValue(0.0)
    r.setMaxOutValue(1.0)
    return r
