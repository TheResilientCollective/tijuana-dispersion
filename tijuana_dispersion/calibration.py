"""
Calibration utilities for the Tijuana H2S dispersion service.

Three things live here:
  1. distributed_channel_sources / distributed_area_sources
     Generators that turn a polyline (channel) or polygon (estuary, bay)
     into a list of SourceSpec at fixed spacing.

  2. run_inversion_bounded
     NNLS variant with archetype-based per-source upper bounds and
     hierarchical shrinkage toward archetype means. Replaces the naive
     unconstrained NNLS in service.run_inversion for production use.

  3. wind_conditional_residuals
     Diagnostic that bins residuals by wind sector at each receptor.
     Systematic per-sector bias points at missing sources in that
     direction.

These keep the service's API surface clean — calibration logic
lives outside the request/response path and gets called from notebooks,
batch jobs, or the demo runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import lsq_linear

from .core import (
    MetCondition,
    Receptor,
    Source,
    forward_run_per_source,
)
from .schemas import SourceSpec

# ---------- Source-field generators ---------- #

# Default upper bounds (g/s) per archetype — physically motivated
# starting points, conservative on the high side. These are caps,
# not targets; the inversion can settle anywhere ≤ bound.
ARCHETYPE_BOUNDS_G_S = {
    "drain": 5.0,  # surface drain; wet weather can be high
    "channel": 2.0,  # diffuse channel pooling
    "estuary": 3.0,  # mudflat area emissions
    "bay": 0.5,  # background bay-pond emissions
    "spill": 20.0,  # event-mode multiplier source
    "unknown": 2.0,
}

# Prior central tendency (g/s) — where shrinkage pulls rates toward
ARCHETYPE_PRIOR_G_S = {
    "drain": 0.5,
    "channel": 0.2,
    "estuary": 0.3,
    "bay": 0.05,
    "spill": 2.0,
    "unknown": 0.2,
}


def distributed_channel_sources(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    n_sources: int,
    archetype: str = "channel",
    seed_rate_g_s: float = 0.1,
    name_prefix: str = "channel",
    height_m: float = 1.0,
) -> list[SourceSpec]:
    """
    Place n_sources evenly along the great-circle line between two points.

    For our scale (a few km), great-circle and rhumb line are identical
    to the meter; this is just linear interpolation in lat/lon.
    """
    lats = np.linspace(start_lat, end_lat, n_sources)
    lons = np.linspace(start_lon, end_lon, n_sources)
    return [
        SourceSpec(
            name=f"{name_prefix}_{i:02d}",
            lat=float(lat),
            lon=float(lon),
            archetype=archetype,
            emission_rate_g_s=seed_rate_g_s,
            height_m=height_m,
        )
        for i, (lat, lon) in enumerate(zip(lats, lons, strict=False))
    ]


def distributed_area_sources(
    bounding_box: tuple[float, float, float, float],
    nx: int,
    ny: int,
    archetype: str = "estuary",
    seed_rate_g_s: float = 0.05,
    name_prefix: str = "area",
    height_m: float = 1.0,
) -> list[SourceSpec]:
    """
    Tile a rectangular area with a grid of point sources.

    bounding_box = (min_lat, min_lon, max_lat, max_lon).
    Result has nx × ny sources at grid centers.
    """
    min_lat, min_lon, max_lat, max_lon = bounding_box
    lat_centers = np.linspace(
        min_lat + (max_lat - min_lat) / (2 * ny),
        max_lat - (max_lat - min_lat) / (2 * ny),
        ny,
    )
    lon_centers = np.linspace(
        min_lon + (max_lon - min_lon) / (2 * nx),
        max_lon - (max_lon - min_lon) / (2 * nx),
        nx,
    )
    sources = []
    idx = 0
    for lat in lat_centers:
        for lon in lon_centers:
            sources.append(
                SourceSpec(
                    name=f"{name_prefix}_{idx:02d}",
                    lat=float(lat),
                    lon=float(lon),
                    archetype=archetype,
                    emission_rate_g_s=seed_rate_g_s,
                    height_m=height_m,
                )
            )
            idx += 1
    return sources


# ---------- Bounded inversion with archetype priors ---------- #


@dataclass
class BoundedInversionResult:
    fitted_rates_g_s: list[float]
    source_names: list[str]
    archetypes: list[str]
    upper_bounds_g_s: list[float]
    residual_rms_ppb: float
    n_observations: int
    n_at_bound: int
    diagnostics: dict[str, Any]


def run_inversion_bounded(
    sources: list[SourceSpec],
    receptors: list[Receptor],
    met: list[MetCondition],
    observations: np.ndarray,
    archetype_bounds: dict[str, float] | None = None,
    archetype_priors: dict[str, float] | None = None,
    prior_lambda: float = 1.0,
    smoothness_lambda: float = 0.0,
) -> BoundedInversionResult:
    """
    Solve E* = argmin_E ||A E - b||² + λ_p ||E - μ||² + λ_s ||L E||²
            s.t. 0 ≤ E_i ≤ B_archetype(i)

    where:
      A = source-receptor footprint matrix (forward model with unit rates)
      b = observations (flattened, masked)
      μ = archetype-prior central tendency, per-source
      B = archetype-derived upper bounds, per-source
      L = first-difference operator over name-prefix groups (smoothness)

    Uses scipy.optimize.lsq_linear, which handles bounded least squares
    via trust-region reflective. Far better behavior than vanilla NNLS
    when sources are co-linear in the receptor space (which they are
    here — three receptors don't separate sources well).
    """
    arche_bounds = archetype_bounds or ARCHETYPE_BOUNDS_G_S
    arche_priors = archetype_priors or ARCHETYPE_PRIOR_G_S

    # Build core sources with unit rates for the footprint matrix
    unit_sources = [
        Source(
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            emission_rate_g_s=1.0,
            height_m=s.height_m,
            archetype=s.archetype,
        )
        for s in sources
    ]

    # Forward run per-source: shape (n_t, n_r, n_s) in ppb
    A_full = forward_run_per_source(unit_sources, receptors, met, units="ppb")
    n_s = A_full.shape[2]

    # Mask missing observations
    valid = ~np.isnan(observations)
    A = A_full[valid]  # (n_valid, n_s)
    b = observations[valid]  # (n_valid,)

    # Build per-source upper bounds and prior means
    bounds_upper = np.array(
        [arche_bounds.get(s.archetype, arche_bounds["unknown"]) for s in sources]
    )
    prior_mean = np.array([arche_priors.get(s.archetype, arche_priors["unknown"]) for s in sources])

    # Augment system for prior shrinkage: add rows λ_p * I, target λ_p * μ
    if prior_lambda > 0:
        reg_A = prior_lambda * np.eye(n_s)
        reg_b = prior_lambda * prior_mean
        A = np.vstack([A, reg_A])
        b = np.concatenate([b, reg_b])

    # Smoothness penalty: first-difference over sources sharing a name prefix
    # (so a chain of channel_00..channel_14 gets pulled toward neighbors).
    if smoothness_lambda > 0:
        # Group sources by name prefix (everything before the last "_NN")
        prefixes = []
        for s in sources:
            parts = s.name.rsplit("_", 1)
            prefixes.append(parts[0] if len(parts) == 2 and parts[1].isdigit() else None)

        L_rows = []
        L_b = []
        for i in range(n_s - 1):
            if prefixes[i] is not None and prefixes[i] == prefixes[i + 1]:
                row = np.zeros(n_s)
                row[i] = smoothness_lambda
                row[i + 1] = -smoothness_lambda
                L_rows.append(row)
                L_b.append(0.0)
        if L_rows:
            A = np.vstack([A, np.array(L_rows)])
            b = np.concatenate([b, np.array(L_b)])

    # Bounded least squares solve
    res = lsq_linear(
        A,
        b,
        bounds=(0.0, bounds_upper),
        method="trf",
        max_iter=2000,
    )
    rates = res.x

    # Diagnostics on original (un-augmented) data
    pred = A_full @ rates  # (n_t, n_r)
    resid = observations - pred
    rms = float(np.sqrt(np.nanmean(resid**2)))
    n_at_bound = int(np.sum(rates >= bounds_upper - 1e-6))

    return BoundedInversionResult(
        fitted_rates_g_s=rates.tolist(),
        source_names=[s.name for s in sources],
        archetypes=[s.archetype for s in sources],
        upper_bounds_g_s=bounds_upper.tolist(),
        residual_rms_ppb=rms,
        n_observations=int(valid.sum()),
        n_at_bound=n_at_bound,
        diagnostics={
            "lsq_cost": float(res.cost),
            "max_predicted": float(np.nanmax(pred)),
            "max_observed": float(np.nanmax(observations)),
            "n_iter": int(res.nit),
            "status": int(res.status),
        },
    )


# ---------- Wind-conditional residual diagnostic ---------- #

WIND_SECTOR_LABELS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]


def wind_conditional_residuals(
    predictions: np.ndarray,
    observations: np.ndarray,
    met: list[MetCondition],
    receptor_names: list[str],
) -> pd.DataFrame:
    """
    Return a DataFrame of mean residual (obs - pred) per wind sector
    per receptor. Sectors are 16 × 22.5°, labeled by compass direction.

    A receptor with positive residual in sector S has under-predicted
    emissions from sources upwind of S — i.e., emissions to the south
    are missing or under-rated when wind blows from the south.
    """
    sector_labels: list[str] = []
    for m in met:
        # 22.5° wide sectors centered on each compass dir.
        # Wind direction is "from" — that's what we want for
        # "what direction did this come from".
        sec_idx = int(((m.wind_direction_deg + 11.25) % 360) / 22.5)
        sector_labels.append(WIND_SECTOR_LABELS[sec_idx])
    sectors = np.array(sector_labels)

    rows = []
    for r_idx, rname in enumerate(receptor_names):
        for sec in WIND_SECTOR_LABELS:
            mask = (sectors == sec) & ~np.isnan(observations[:, r_idx])
            if mask.sum() == 0:
                continue
            obs_s = observations[mask, r_idx]
            pred_s = predictions[mask, r_idx]
            resid = obs_s - pred_s
            rows.append(
                {
                    "receptor": rname,
                    "wind_sector": sec,
                    "n_hours": int(mask.sum()),
                    "obs_mean": float(obs_s.mean()),
                    "pred_mean": float(pred_s.mean()),
                    "resid_mean": float(resid.mean()),
                    "resid_rms": float(np.sqrt((resid**2).mean())),
                }
            )
    return pd.DataFrame(rows)
