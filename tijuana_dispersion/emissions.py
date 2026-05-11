"""
River/estuary emissions model — skeleton.

This is a starting framework, NOT a finished model. The architecture is
designed to integrate with an existing emissions implementation (e.g.,
the one in the geodemic repository) as a drop-in replacement for any of
the parametric functions below.

Design principle: emissions and dispersion are SEPARATE concerns.
Emissions take physical drivers and produce per-source emission rates;
dispersion takes those rates and produces concentrations at receptors.
This module produces inputs for the dispersion service, not outputs.

See emissions_model_spec.md for the full architecture rationale.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from .schemas import SourceSpec

# ---------- Driver bundle ---------- #


@dataclass
class EmissionDrivers:
    """
    Hourly drivers needed to compute emission rates.

    Built from one row of the modeldata_h2s_nofill dataframe per timestep.
    Same instance feeds all sources at that timestep — only source-specific
    location modifies their response.
    """

    timestamp: str
    temperature_c: float
    wind_speed_10m_ms: float
    sbiwtp_flow_mgd: float
    sbiwtp_deficit: float
    tide_height_m: float
    is_night: bool
    border_flow_m3s: float | None = None
    precipitation_mm: float = 0.0

    @classmethod
    def from_dataframe_row(cls, row: Any, ts_col: str = "time") -> EmissionDrivers:
        """Build from a pandas row using modeldata_h2s_nofill column names."""
        return cls(
            timestamp=str(row[ts_col]),
            temperature_c=float(row["temperature_2m"]),
            wind_speed_10m_ms=float(row["wind_speed_10m"]),
            sbiwtp_flow_mgd=float(row["sbiwtp_flow_mgd"]),
            sbiwtp_deficit=float(row["sbiwtp_deficit"]),
            tide_height_m=float(row["tide_height"]),
            is_night=bool(row["is_night"] >= 0.5),
            border_flow_m3s=float(row.get("Flow (m^3/s)--Border", float("nan"))),
            precipitation_mm=float(row.get("precipitation", 0.0) or 0.0),
        )


# ---------- Parameter set ---------- #


@dataclass
class EmissionParameters:
    """
    The set of fitted parameters. Defaults are literature priors;
    calibration finds posterior values.
    """

    # Temperature (Q10)
    Q10: float = 2.5
    T_ref_c: float = 20.0

    # Substrate (inverse SBIWTP throughput)
    substrate_alpha: float = 0.05  # per (deficit unit)
    substrate_threshold_mgd: float = 25.0

    # Volatilization (Wanninkhof k_w intercept; H_S/HS- partition is fixed)
    k_w_ref_cm_h: float = 4.0  # m/s wind reference at 5 m/s
    pH_per_archetype: dict[str, float] = field(  # noqa: N815  (pH is correct chemistry notation)
        default_factory=lambda: {
            "drain": 7.0,
            "channel": 7.2,
            "estuary": 7.5,
            "bay": 8.0,
            "spill": 7.0,
        }
    )

    # Diurnal modifier (smooth nocturnal enhancement)
    diel_amplitude: float = 1.5  # multiplier at peak (night) over day
    diel_phase_hours: float = 4.0  # hours past midnight at peak

    # Archetype scalars
    f_arch: dict[str, float] = field(
        default_factory=lambda: {
            "drain": 1.0,
            "channel": 0.3,
            "estuary": 0.5,
            "bay": 0.05,
            "spill": 5.0,
        }
    )

    # Per-source baseline rates (g/s); fit during calibration.
    # Keyed by source name. Sources not in this dict get 0.0.
    baselines_g_s: dict[str, float] = field(default_factory=dict)


# ---------- Parametric functions ---------- #


def f_temperature(T: float, params: EmissionParameters) -> float:
    """Q10 temperature modifier."""
    return float(params.Q10 ** ((T - params.T_ref_c) / 10.0))


def f_substrate(driver: EmissionDrivers, params: EmissionParameters) -> float:
    """
    Substrate availability for SRB. Inverse of SBIWTP throughput:
    when SBIWTP is processing more sewage, less reaches the river.

    Default form is a piecewise linear ramp; replace with the
    geodemic-repo function once we wire it in.
    """
    deficit = max(0.0, params.substrate_threshold_mgd - driver.sbiwtp_flow_mgd)
    return 1.0 + params.substrate_alpha * deficit


def f_volatilization(driver: EmissionDrivers, params: EmissionParameters, archetype: str) -> float:
    """
    Air-water gas transfer factor combining wind-driven k_w and
    pH-dependent H2S(aq) fraction.

    Wanninkhof 2014 form for k_w: k = 0.31 * U10^2 * (Sc/660)^-0.5
    For our scale, we use a normalized form with k_w_ref as scaling.
    """
    U10 = max(0.5, driver.wind_speed_10m_ms)
    k_w_factor = (U10 / 5.0) ** 2.0  # quadratic in wind, ref=5 m/s

    pH = params.pH_per_archetype.get(archetype, 7.0)
    pKa = 7.0  # H2S/HS- at 25C
    H2S_fraction = 1.0 / (1.0 + 10.0 ** (pH - pKa))
    return float(k_w_factor * H2S_fraction)


def f_diel(driver: EmissionDrivers, params: EmissionParameters) -> float:
    """
    Smooth diurnal modifier: emissions peak at night (default phase 04:00).
    The is_night flag in the drivers gives a coarse signal; we use a
    smooth cosine for differentiability under optimization.
    """
    # Parse hour from timestamp
    try:
        ts = datetime.fromisoformat(driver.timestamp.replace("Z", "+00:00"))
        hour = ts.hour + ts.minute / 60.0
    except (ValueError, AttributeError):
        # Fall back to a coarse day/night split when the timestamp is missing
        # or malformed — the diurnal modifier degrades gracefully.
        hour = 3.0 if driver.is_night else 12.0

    # Cosine peaking at diel_phase_hours; baseline 1.0, peak diel_amplitude
    angle = 2 * math.pi * (hour - params.diel_phase_hours) / 24.0
    # cos goes from -1..+1; map to (1, amplitude)
    return 1.0 + 0.5 * (params.diel_amplitude - 1.0) * (1.0 + math.cos(angle))


# ---------- Model ---------- #


@dataclass
class SourceSpecLocation:
    """Lightweight locator: defines a source's identity and archetype
    without committing to an emission rate yet."""

    name: str
    lat: float
    lon: float
    archetype: str
    height_m: float = 1.0


class EmissionsModel:
    """
    Given a set of fitted parameters and a list of source locations,
    produce SourceSpec objects with populated emission_rate_g_s for
    a given timestep.
    """

    def __init__(self, parameters: EmissionParameters):
        self.params = parameters

    def emission_rate_g_s(
        self,
        location: SourceSpecLocation,
        driver: EmissionDrivers,
    ) -> float:
        """Compute E_i(t) for a single source at a single timestep."""
        E0 = self.params.baselines_g_s.get(location.name, 0.0)
        if E0 <= 0:
            return 0.0
        return (
            E0
            * self.params.f_arch.get(location.archetype, 1.0)
            * f_temperature(driver.temperature_c, self.params)
            * f_substrate(driver, self.params)
            * f_volatilization(driver, self.params, location.archetype)
            * f_diel(driver, self.params)
        )

    def compute_sources(
        self,
        locations: list[SourceSpecLocation],
        driver: EmissionDrivers,
    ) -> list[SourceSpec]:
        """Return a SourceSpec per location with the populated rate."""
        return [
            SourceSpec(
                name=loc.name,
                lat=loc.lat,
                lon=loc.lon,
                archetype=loc.archetype,
                height_m=loc.height_m,
                emission_rate_g_s=self.emission_rate_g_s(loc, driver),
            )
            for loc in locations
        ]

    def compute_sources_timeseries(
        self,
        locations: list[SourceSpecLocation],
        drivers: list[EmissionDrivers],
    ) -> np.ndarray:
        """
        Vectorized variant: rates of shape (n_times, n_sources).
        Useful for inversion where we want the full time-source matrix.
        """
        n_t = len(drivers)
        n_s = len(locations)
        out = np.zeros((n_t, n_s))
        for t_idx, drv in enumerate(drivers):
            for s_idx, loc in enumerate(locations):
                out[t_idx, s_idx] = self.emission_rate_g_s(loc, drv)
        return out


# ---------- Bridge points for an external emissions model ---------- #

# These hooks let us swap in a function from the geodemic-repo
# emissions implementation without changing the rest of the architecture.
# Set any of these to None to use the default parametric form.

ExternalSubstrateFn = Callable[[EmissionDrivers, EmissionParameters], float]
ExternalDielFn = Callable[[EmissionDrivers, EmissionParameters], float]
ExternalVolatilizationFn = Callable[[EmissionDrivers, EmissionParameters, str], float]


def make_emissions_model_with_overrides(
    parameters: EmissionParameters,
    substrate_fn: ExternalSubstrateFn | None = None,
    diel_fn: ExternalDielFn | None = None,
    volatilization_fn: ExternalVolatilizationFn | None = None,
) -> EmissionsModel:
    """
    Construct an EmissionsModel with one or more functional forms
    overridden by an externally-supplied implementation.

    Use this to plug in the geodemic-repo emissions logic for
    f_substrate while keeping the diurnal and volatilization defaults,
    or any other combination. When no overrides are supplied, behaves
    exactly like ``EmissionsModel(parameters)``.
    """
    if substrate_fn is None and diel_fn is None and volatilization_fn is None:
        return EmissionsModel(parameters)

    # Capture the overrides in a subclass so we replace behavior cleanly
    # instead of monkey-patching an instance method.
    class _OverriddenModel(EmissionsModel):
        def emission_rate_g_s(
            self,
            location: SourceSpecLocation,
            driver: EmissionDrivers,
        ) -> float:
            E0 = self.params.baselines_g_s.get(location.name, 0.0)
            if E0 <= 0:
                return 0.0
            sub = (
                substrate_fn(driver, self.params)
                if substrate_fn is not None
                else f_substrate(driver, self.params)
            )
            vol = (
                volatilization_fn(driver, self.params, location.archetype)
                if volatilization_fn is not None
                else f_volatilization(driver, self.params, location.archetype)
            )
            diel = (
                diel_fn(driver, self.params) if diel_fn is not None else f_diel(driver, self.params)
            )
            return float(
                E0
                * self.params.f_arch.get(location.archetype, 1.0)
                * f_temperature(driver.temperature_c, self.params)
                * sub
                * vol
                * diel
            )

    return _OverriddenModel(parameters)
