"""
Atmospheric regime classification.

The Gaussian-plume backends in this service model *advective* transport
from upwind sources. Calibration work in ``tijuana-dispersion-experiments``
(experiments v3 → v3.6) established that they have effectively zero skill
in the calm-nocturnal **stagnation** regime: H2S accumulates locally
under a collapsed stable boundary layer with no preferred wind
direction, and a steady-state plume (concentration ∝ 1/u, requiring a
meaningful wind direction) cannot represent it.

This module provides the regime classifier used as a guardrail
(issue #2): when a request's meteorology is calm-nocturnal, the service
flags the result as out-of-envelope rather than presenting a confident
low concentration. The same classifier is intended to drive backend
dispatch once a dedicated stagnation model exists (issue #3).
"""

from __future__ import annotations

from .core import MetCondition

#: Wind speed (m/s) at or above which transport is treated as advective.
#: Below this *and* at night, the plume model is out of its envelope.
#: Chosen from the experiments-repo finding that Berry's >100 ppb hours
#: have median wind ~2.4 m/s; 2.5 m/s is a conservative cut.
DEFAULT_U_CALM_MS = 2.5


def is_stagnation(met: MetCondition, u_calm: float = DEFAULT_U_CALM_MS) -> bool:
    """Classify a single meteorological hour as calm-nocturnal stagnation.

    Parameters
    ----------
    met : MetCondition
        The hour's meteorology. Only ``is_night`` and ``wind_speed_ms``
        are used.
    u_calm : float, optional
        Wind-speed threshold in m/s. An hour is stagnation when it is
        night and ``wind_speed_ms`` is strictly below this value.
        Defaults to :data:`DEFAULT_U_CALM_MS`.

    Returns
    -------
    bool
        ``True`` if the hour is in the calm-nocturnal stagnation regime
        (plume model out of envelope), ``False`` otherwise.

    Notes
    -----
    This v1 classifier intentionally uses only the night flag and wind
    speed — the smallest robust rule. A Pasquill E/F refinement is
    deferred to the dedicated stagnation backend work (issue #3).
    """
    return bool(met.is_night and met.wind_speed_ms < u_calm)
