"""
Gaussian plume dispersion core for Tijuana River Valley H2S modeling.

Self-contained pure-Python/numpy implementation. Designed as one
backend behind the unified DispersionService interface — HYSPLIT
and other models slot in alongside.

Physics: Briggs urban/rural dispersion coefficients with Pasquill
stability inferred from wind speed, time-of-day, and cloud cover.
Single-receptor concentration uses standard Gaussian plume with
ground reflection (effective stack height = 0 for area sources at
ground level).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

# Earth radius for great-circle distance (m)
R_EARTH = 6371000.0


def latlon_to_local_xy(
    lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float
) -> tuple[np.ndarray, np.ndarray]:
    """Equirectangular projection to local meters, accurate enough at this scale."""
    lat_rad = np.radians(lat)
    lat0_rad = math.radians(lat0)
    x = R_EARTH * np.radians(lon - lon0) * math.cos(lat0_rad)
    y = R_EARTH * (lat_rad - lat0_rad)
    return x, y


def pasquill_stability(
    wind_speed_ms: float,
    is_night: bool,
    cloud_cover_frac: float = 0.5,
) -> str:
    """
    Pasquill stability class A-F from wind speed and insolation/cloud.
    Simplified table — adequate for area-source dispersion at this scale.
    A=very unstable, F=very stable. Returns letter.
    """
    u = wind_speed_ms
    if is_night:
        # Night: cloud cover proxies for thermal stratification
        if cloud_cover_frac < 0.5:
            # clear sky, strong radiative cooling -> very stable
            if u < 2.0:
                return "F"
            if u < 3.0:
                return "E"
            if u < 5.0:
                return "D"
            return "D"
        # overcast, less stable
        if u < 2.0:
            return "E"
        if u < 5.0:
            return "D"
        return "D"
    # Day: assume moderate insolation (could refine with solar elev)
    if u < 2.0 or u < 3.0:
        return "B"
    if u < 5.0:
        return "C"
    if u < 6.0:
        return "D"
    return "D"


# Briggs (rural) dispersion coefficients σy, σz = a*x*(1+b*x)^c
# σy: a, b, c   σz: a, b, c    (x in meters)
BRIGGS_RURAL = {
    "A": {"sy": (0.22, 0.0001, -0.5), "sz": (0.20, 0.0, 1.0)},
    "B": {"sy": (0.16, 0.0001, -0.5), "sz": (0.12, 0.0, 1.0)},
    "C": {"sy": (0.11, 0.0001, -0.5), "sz": (0.08, 0.0002, -0.5)},
    "D": {"sy": (0.08, 0.0001, -0.5), "sz": (0.06, 0.0015, -0.5)},
    "E": {"sy": (0.06, 0.0001, -0.5), "sz": (0.03, 0.0003, -1.0)},
    "F": {"sy": (0.04, 0.0001, -0.5), "sz": (0.016, 0.0003, -1.0)},
}


def briggs_sigma(stability: str, x_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute σy, σz at downwind distance x (m) for given stability class."""
    coef = BRIGGS_RURAL[stability]
    a_y, b_y, c_y = coef["sy"]
    a_z, b_z, c_z = coef["sz"]
    x_safe = np.maximum(x_m, 1.0)
    sigma_y = a_y * x_safe * np.power(1.0 + b_y * x_safe, c_y)
    sigma_z = a_z * x_safe * np.power(1.0 + b_z * x_safe, c_z)
    return sigma_y, sigma_z


@dataclass
class Source:
    """A single emission source."""

    name: str
    lat: float
    lon: float
    emission_rate_g_s: float  # H2S in g/s
    height_m: float = 1.0  # effective stack height
    archetype: str = "unknown"  # drain | channel | estuary | bay


@dataclass
class Receptor:
    """A monitoring station."""

    name: str
    lat: float
    lon: float
    height_m: float = 2.0


@dataclass
class MetCondition:
    """Single hourly meteorological condition."""

    timestamp: str  # ISO 8601
    wind_speed_ms: float
    wind_direction_deg: float  # meteorological convention: from
    temperature_c: float
    cloud_cover_frac: float
    is_night: bool


def gaussian_plume_concentration(
    source: Source,
    receptor: Receptor,
    met: MetCondition,
    min_wind_ms: float = 0.5,
) -> float:
    """
    Steady-state Gaussian plume concentration at a receptor in µg/m³.

    Convert to ppb at end if needed (for H2S at 25°C, 1 atm:
    1 ppb ≈ 1.39 µg/m³, so ppb = µg/m³ / 1.39).
    """
    # Project to local frame centered on source
    rx_arr, ry_arr = latlon_to_local_xy(
        np.array([receptor.lat]),
        np.array([receptor.lon]),
        source.lat,
        source.lon,
    )
    rx = float(rx_arr[0])
    ry = float(ry_arr[0])

    # Rotate so wind blows along +x.
    # Meteorological wind direction is "from" measured CW from N.
    # Convert to "to" direction, then project receptor.
    # If wind blows TO bearing φ (CW from N), then
    #   downwind  = east * sin(φ) + north * cos(φ)
    #   crosswind = east * cos(φ) - north * sin(φ)
    # (with crosswind positive to the right of the wind direction).
    wind_to_deg = (met.wind_direction_deg + 180.0) % 360.0
    phi = math.radians(wind_to_deg)
    sin_p, cos_p = math.sin(phi), math.cos(phi)
    x = rx * sin_p + ry * cos_p  # downwind
    y = rx * cos_p - ry * sin_p  # crosswind

    if x <= 0:
        # Receptor is upwind of source — no plume contribution
        return 0.0

    u = max(met.wind_speed_ms, min_wind_ms)
    stab = pasquill_stability(u, met.is_night, met.cloud_cover_frac)
    sy_arr, sz_arr = briggs_sigma(stab, np.array([x]))
    sy = float(sy_arr[0])
    sz = float(sz_arr[0])

    H = source.height_m
    z = receptor.height_m

    # Gaussian plume with ground reflection
    Q = source.emission_rate_g_s * 1e6  # g/s → µg/s
    pref = Q / (2.0 * math.pi * u * sy * sz)
    crosswind = math.exp(-0.5 * (y / sy) ** 2)
    vertical = math.exp(-0.5 * ((z - H) / sz) ** 2) + math.exp(-0.5 * ((z + H) / sz) ** 2)
    return float(pref * crosswind * vertical)  # µg/m³


def ugm3_to_ppb_h2s(ugm3: float, temp_c: float = 25.0) -> float:
    """H2S: MW=34.08 g/mol. ppb = (µg/m³) × 24.45 / 34.08 at 25°C, 1 atm."""
    # Adjust molar volume slightly for temperature
    Vm = 24.45 * (273.15 + temp_c) / (273.15 + 25.0)
    return ugm3 * Vm / 34.08


def forward_run(
    sources: list[Source],
    receptors: list[Receptor],
    met_series: list[MetCondition],
    units: Literal["ppb", "ugm3"] = "ppb",
) -> np.ndarray:
    """
    Run the forward model for a list of sources × receptors × times.

    Returns: ndarray of shape (n_times, n_receptors) with summed contribution
    from all sources. To get per-source contribution, call this once per source
    or use forward_run_per_source.
    """
    n_t = len(met_series)
    n_r = len(receptors)
    out = np.zeros((n_t, n_r))

    for t_idx, met in enumerate(met_series):
        for r_idx, rec in enumerate(receptors):
            total = 0.0
            for src in sources:
                ugm3 = gaussian_plume_concentration(src, rec, met)
                if units == "ppb":
                    total += ugm3_to_ppb_h2s(ugm3, met.temperature_c)
                else:
                    total += ugm3
            out[t_idx, r_idx] = total
    return out


def forward_run_per_source(
    sources: list[Source],
    receptors: list[Receptor],
    met_series: list[MetCondition],
    units: Literal["ppb", "ugm3"] = "ppb",
) -> np.ndarray:
    """
    Per-source contribution array, useful for inversion.

    Returns: ndarray of shape (n_times, n_receptors, n_sources).
    Linear in emission rate, so this gives the 'source-receptor matrix'
    that NNLS inversion needs.
    """
    n_t = len(met_series)
    n_r = len(receptors)
    n_s = len(sources)
    out = np.zeros((n_t, n_r, n_s))

    for t_idx, met in enumerate(met_series):
        for r_idx, rec in enumerate(receptors):
            for s_idx, src in enumerate(sources):
                ugm3 = gaussian_plume_concentration(src, rec, met)
                if units == "ppb":
                    out[t_idx, r_idx, s_idx] = ugm3_to_ppb_h2s(ugm3, met.temperature_c)
                else:
                    out[t_idx, r_idx, s_idx] = ugm3
    return out
