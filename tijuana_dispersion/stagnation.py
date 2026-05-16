"""
Calm-night stagnation box (accumulation) model — service issue #3.

Motivation
----------
The Gaussian-plume backends have ~zero skill in the calm-nocturnal
regime (experiments v3 → v3.6 and the 2026-05-15 calm-night wind
reanalysis: "you cannot trap a plume that never arrived"). When the
nocturnal surface layer decouples and collapses, the right zeroth-order
physics is not advective transport but *accumulation in a shallow,
poorly-ventilated box*:

    dC/dt = E_local / (A · H_mix)  −  C / τ

with the exact discrete update over a step Δt

    C[t] = C[t-1]·e^(−Δt/τ)  +  C* · (1 − e^(−Δt/τ))

    C* = (E_local · 1e6) · (τ · 3600) / (A · H_mix)   [µg/m³]

C* is the analytic fixed point (steady state) the box relaxes toward
under constant forcing; the update is exact for a piecewise-constant
source, so it is unconditionally stable for any Δt.

H_mix is keyed off the Pasquill stability class (shallower box for
more stable air; the collapsed nocturnal SBL is the F row). The first
sample advances from ``c_init`` by one default step (1 h) since it has
no predecessor — so a single stagnation hour already accumulates a
non-zero concentration, which the regime dispatch in ``service`` needs.

Parameter calibration (τ, H_mix table, the neighbourhood area A, and
the local emission split) against the 242 Berry >100 ppb hours is an
*experiments-repo* follow-up: no calibration data lives in this
service repo. The defaults here are physically-reasonable
placeholders, explicitly uncalibrated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np

from .core import MetCondition, pasquill_stability, ugm3_to_ppb_h2s

# Mixing depth (m) by Pasquill stability class. Deep, well-mixed
# convective boundary layer for unstable A; a collapsed, decoupled
# nocturnal surface layer for very-stable F. Monotone A→F. These are
# textbook order-of-magnitude values, uncalibrated (see module docstring).
H_MIX_BY_STABILITY_M: dict[str, float] = {
    "A": 1600.0,
    "B": 1200.0,
    "C": 800.0,
    "D": 500.0,
    "E": 200.0,
    "F": 50.0,
}

# Default step used for the very first sample (no predecessor timestamp)
# and whenever timestamps cannot be parsed.
_DEFAULT_STEP_H = 1.0


@dataclass
class StagnationBoxParams:
    """Box-model parameters.

    tau_h:        ventilation/decay timescale of the box (hours).
    e_local_g_s:  local H2S emission feeding the box (g/s).
    area_m2:      horizontal footprint of the accumulation box (m²).
    """

    tau_h: float = 3.0
    e_local_g_s: float = 1.0
    area_m2: float = 4.0e6


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _step_hours(met: list[MetCondition]) -> list[float]:
    """Δt (h) for each sample. First sample uses the default step; later
    samples use the wall-clock gap to the previous timestamp (so a
    2-hour gap takes a correspondingly larger step)."""
    steps: list[float] = []
    prev: datetime | None = None
    for m in met:
        cur = _parse(m.timestamp)
        if prev is None or cur is None:
            steps.append(_DEFAULT_STEP_H)
        else:
            dt_h = (cur - prev).total_seconds() / 3600.0
            steps.append(dt_h if dt_h > 0.0 else _DEFAULT_STEP_H)
        prev = cur if cur is not None else prev
    return steps


def box_series(
    met: list[MetCondition],
    params: StagnationBoxParams,
    units: Literal["ppb", "ugm3"] = "ppb",
    c_init: float = 0.0,
) -> np.ndarray:
    """Integrate the box recurrence over a met series.

    Returns a 1-D array of length ``len(met)`` (concentration is
    receptor-independent in this v1 model). ``units='ugm3'`` returns
    µg/m³; ``'ppb'`` converts each sample with the H2S molar volume at
    that sample's temperature.
    """
    n = len(met)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out

    e_ug_s = params.e_local_g_s * 1.0e6  # g/s → µg/s
    tau_s = params.tau_h * 3600.0
    steps = _step_hours(met)

    c = float(c_init)
    for i, (m, dt_h) in enumerate(zip(met, steps, strict=True)):
        stab = pasquill_stability(m.wind_speed_ms, m.is_night, m.cloud_cover_frac)
        h_mix = H_MIX_BY_STABILITY_M[stab]
        # Analytic fixed point C* = E·τ / (A·H_mix)  [µg/m³].
        c_star = e_ug_s * tau_s / (params.area_m2 * h_mix)
        decay = math.exp(-(dt_h * 3600.0) / tau_s)
        c = c * decay + c_star * (1.0 - decay)
        out[i] = c if units == "ugm3" else ugm3_to_ppb_h2s(c, m.temperature_c)
    return out
