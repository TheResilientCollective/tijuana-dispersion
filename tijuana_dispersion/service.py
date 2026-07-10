"""
Service-layer interface: dispatches typed requests to the chosen
backend, handles caching, returns typed responses.

This is what FastAPI (or an MCP server, or a CLI) wraps. The caching
is filesystem-based and content-addressed (hash of canonical JSON
input) so repeated calls during calibration loops are free.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

from .backends import StagnationBoxBackend
from .core import (
    MetCondition,
    Receptor,
    Source,
    forward_run,
    forward_run_per_source,
)
from .regime import is_stagnation
from .schemas import (
    EmissionDriverParams,
    ForwardRunRequest,
    ForwardRunResult,
    InversionRequest,
    InversionResult,
    MetSpec,
    ReceptorSpec,
    SourceSpec,
)
from .stagnation import (
    StagnationBoxParams,
    TemperatureEmissionParams,
    box_series,
    temperature_led_e_local,
)

# Cache directory is configurable via DISPERSION_CACHE_DIR. The default lives
# under the OS temp dir so the package imports cleanly on any platform; in
# production set the env var to a persistent path (e.g. a Railway volume).
CACHE_DIR = Path(
    os.environ.get(
        "DISPERSION_CACHE_DIR",
        str(Path(tempfile.gettempdir()) / "tijuana_dispersion_cache"),
    )
)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _hash_request(req: ForwardRunRequest) -> str:
    payload = req.model_dump_json(exclude={"cache_key", "notes"})
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _to_core_sources(specs: list[SourceSpec]) -> list[Source]:
    return [
        Source(
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            emission_rate_g_s=s.emission_rate_g_s,
            height_m=s.height_m,
            archetype=s.archetype,
        )
        for s in specs
    ]


def _to_core_receptors(specs: list[ReceptorSpec]) -> list[Receptor]:
    return [Receptor(name=r.name, lat=r.lat, lon=r.lon, height_m=r.height_m) for r in specs]


def _to_core_met(specs: list[MetSpec]) -> list[MetCondition]:
    return [
        MetCondition(
            timestamp=m.timestamp,
            wind_speed_ms=m.wind_speed_ms,
            wind_direction_deg=m.wind_direction_deg,
            temperature_c=m.temperature_c,
            cloud_cover_frac=m.cloud_cover_frac,
            is_night=m.is_night,
            mixing_height_m=m.mixing_height_m,
        )
        for m in specs
    ]


def _box_array(
    sources: list[Source],
    receptors: list[Receptor],
    met: list[MetCondition],
    req: ForwardRunRequest,
) -> np.ndarray:
    """Box concentration (n_times, n_receptors) for the stagnation
    regime. With ``emission_driver`` off this is exactly the issue-#3
    constant box (StagnationBoxBackend). With it on, ``E_local``
    becomes the temperature-led, time-varying series (issue #6);
    receptor-independent, so the column is broadcast."""
    if not req.emission_driver:
        return StagnationBoxBackend().run_forward(sources, receptors, met, units=req.units)
    edp = req.emission_driver_params or EmissionDriverParams()
    e0 = edp.e0_g_s if edp.e0_g_s is not None else float(sum(s.emission_rate_g_s for s in sources))
    e_series = temperature_led_e_local(
        met, TemperatureEmissionParams(e0_g_s=e0, q10=edp.q10, t_ref_c=edp.t_ref_c)
    )
    series = box_series(met, StagnationBoxParams(e_local_g_s=e_series), units=req.units)
    return np.repeat(series[:, None], len(receptors), axis=1)


def run_forward(req: ForwardRunRequest) -> ForwardRunResult:
    """Execute a forward dispersion request."""
    cache_id = req.cache_key or _hash_request(req)
    cache_path = CACHE_DIR / f"forward_{cache_id}.json"

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        cached["cached"] = True
        return ForwardRunResult(**cached)

    if req.backend == "hysplit":
        # Stub — would shell out to containerized HYSPLIT here
        raise NotImplementedError(
            "HYSPLIT backend not yet wired; install container "
            "and implement subprocess call. The interface and "
            "cache layer are ready."
        )

    sources = _to_core_sources(req.sources)
    receptors = _to_core_receptors(req.receptors)
    met = _to_core_met(req.meteorology)

    # Stagnation guardrail (issue #2): flag calm-nocturnal hours where the
    # plume model is out of its envelope rather than presenting a
    # confident low concentration.
    stagnation_flags = [is_stagnation(m) for m in met]
    n_stagnation = sum(stagnation_flags)
    out_of_envelope = n_stagnation > 0

    t0 = time.time()
    if req.backend == "stagnation_box":
        # Explicitly force the accumulation box for every hour.
        if req.return_per_source:
            # Per-source view is receptor/emission-lumped; the
            # emission driver (a single lumped E_local series) does
            # not split per source, so keep the constant per-source
            # box here (issue #6 driver applies to the 2-D path).
            arr = StagnationBoxBackend().run_forward_per_source(
                sources, receptors, met, units=req.units
            )
        else:
            arr = _box_array(sources, receptors, met, req)
        dispatch = "forced_box"
    elif req.return_per_source:
        arr = forward_run_per_source(sources, receptors, met, units=req.units)
        dispatch = "disabled" if req.disable_regime_dispatch else "regime"
    else:
        arr = forward_run(sources, receptors, met, units=req.units)
        if req.disable_regime_dispatch:
            dispatch = "disabled"
        else:
            # Regime dispatch (issue #3): on stagnation timesteps the
            # Gaussian plume has ~no skill, so overlay the accumulation
            # box on exactly those hours; advective hours stay Gaussian.
            dispatch = "regime"
            if out_of_envelope:
                box_arr = _box_array(sources, receptors, met, req)
                for t_idx, flagged in enumerate(stagnation_flags):
                    if flagged:
                        arr[t_idx, :] = box_arr[t_idx, :]
    runtime_ms = int((time.time() - t0) * 1000)

    summary = {
        "max_concentration": float(np.max(arr)),
        "mean_concentration": float(np.mean(arr)),
        "n_nonzero": int(np.sum(arr > 0.001)),
        "n_stagnation_hours": n_stagnation,
        "regime": "stagnation" if out_of_envelope else "advective",
        "dispatch": dispatch,
        "emission_driver": bool(req.emission_driver),
    }

    result = ForwardRunResult(
        backend=req.backend,
        n_times=len(met),
        n_receptors=len(receptors),
        n_sources=len(sources),
        units=req.units,
        receptor_names=[r.name for r in receptors],
        timestamps=[m.timestamp for m in met],
        concentrations=arr.tolist(),
        summary=summary,
        runtime_ms=runtime_ms,
        stagnation_flags=stagnation_flags,
        out_of_envelope=out_of_envelope,
    )
    cache_path.write_text(result.model_dump_json())
    return result


def run_inversion(req: InversionRequest) -> InversionResult:
    """NNLS inversion to fit emission rates from observations."""
    # Build the source-receptor footprint matrix using forward model
    # with unit emission rates
    unit_sources = [
        Source(
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            emission_rate_g_s=1.0,
            height_m=s.height_m,
            archetype=s.archetype,
        )
        for s in req.sources
    ]
    receptors = _to_core_receptors(req.receptors)
    met = _to_core_met(req.meteorology)

    # Per-source unit-rate concentrations: shape (n_t, n_r, n_s)
    A_full = forward_run_per_source(unit_sources, receptors, met, units="ppb")

    obs = np.array(req.observations, dtype=float)  # (n_t, n_r)
    # Mask missing obs
    valid = ~np.isnan(obs)
    A = A_full[valid]  # (n_valid, n_s)
    b = obs[valid]  # (n_valid,)

    if req.l1_lambda > 0:
        # Augment for L1-style shrinkage (NNLS with regularization)
        n_s = A.shape[1]
        reg_A = req.l1_lambda * np.eye(n_s)
        reg_b = np.zeros(n_s)
        A = np.vstack([A, reg_A])
        b = np.concatenate([b, reg_b])

    rates, residual = nnls(A, b, maxiter=2000)

    # Compute fit diagnostics on original (non-augmented) data
    pred = A_full @ rates  # (n_t, n_r)
    resid = obs - pred
    rms = float(np.sqrt(np.nanmean(resid**2)))

    return InversionResult(
        fitted_rates_g_s=rates.tolist(),
        source_names=[s.name for s in req.sources],
        residual_rms=rms,
        fit_diagnostics={
            "nnls_residual": float(residual),
            "n_observations": int(valid.sum()),
            "n_sources": len(req.sources),
            "max_predicted": float(np.nanmax(pred)),
            "max_observed": float(np.nanmax(obs)),
        },
    )
