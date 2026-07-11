"""
Pydantic schemas defining the dispersion service API contract.

These are the structures Claude (or any client) sends as JSON to
request a run. Versioned so the contract can evolve without breaking
old clients.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.5.0"


class SourceSpec(BaseModel):
    name: str
    lat: float
    lon: float
    emission_rate_g_s: float
    height_m: float = 1.0
    archetype: str = "unknown"


class ReceptorSpec(BaseModel):
    name: str
    lat: float
    lon: float
    height_m: float = 2.0


class MetSpec(BaseModel):
    timestamp: str
    wind_speed_ms: float
    wind_direction_deg: float
    temperature_c: float
    cloud_cover_frac: float = 0.5
    is_night: bool
    # Atmospheric mixing height (m). None => unbounded vertical mixing
    # (original behavior); when set, the plume reflects off a lid at this
    # height. See core.gaussian_plume_concentration.
    mixing_height_m: float | None = None


class EmissionDriverParams(BaseModel):
    """Temperature-led emission-driver parameters (schema 0.4.0,
    issue #6). When the driver is enabled, the stagnation box's
    local emission becomes time-varying:

        E_local(t) = e0_g_s · q10 ** ((T(t) − t_ref_c) / 10)

    ``e0_g_s = None`` means "use the sum of the request's source
    emission rates as E0" (same lumped convention as the constant
    box). Defaults are uncalibrated literature values; calibrating
    them is an experiments-repo follow-up.
    """

    q10: float = 2.5
    t_ref_c: float = 20.0
    e0_g_s: float | None = None


class StagnationBoxSpec(BaseModel):
    """Stagnation-box overrides (schema 0.5.0, issue #3 follow-up).

    ``lambda_m`` switches the box from the lumped, receptor-independent
    v1 to a **receptor-dependent** model: each receptor's box is fed by
    ``E_r = Σ_s rate_s · exp(−d_rs / lambda_m)``, so proximity to a
    source (Berry ← Saturn Blvd Bridge, 0.9 km) finally matters on calm
    nights. ``None`` keeps v1 exactly. ``tau_h``/``area_m2`` expose the
    box constants for calibration; defaults match
    :class:`stagnation.StagnationBoxParams`.
    """

    lambda_m: float | None = Field(default=None, gt=0.0)
    tau_h: float = Field(default=3.0, gt=0.0)
    area_m2: float = Field(default=4.0e6, gt=0.0)
    # Drainage-flow variant (Saturn Blvd mechanism, 2026-07-11): when set,
    # the kernel becomes directional — receptors accumulate sources
    # *upstream* along the drainage bearing (direction the flow moves
    # toward, CW from north; Tijuana valley ≈ 280°) with lambda_m as the
    # along-valley decay and lambda_cross_m as the short cross-valley /
    # counter-drainage decay. Requires lambda_m.
    drainage_bearing_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    lambda_cross_m: float = Field(default=500.0, gt=0.0)


class ForwardRunRequest(BaseModel):
    """Request for a forward dispersion run."""

    schema_version: str = SCHEMA_VERSION
    backend: Literal["gaussian_plume", "stagnation_box", "hysplit"] = "gaussian_plume"
    sources: list[SourceSpec]
    receptors: list[ReceptorSpec]
    meteorology: list[MetSpec]
    units: Literal["ppb", "ugm3"] = "ppb"
    return_per_source: bool = False
    # Regime dispatch (schema 0.3.0): with the default gaussian_plume
    # backend, calm-nocturnal stagnation timesteps are routed to the
    # StagnationBoxBackend (the Gaussian plume has ~no skill there).
    # Set True to disable dispatch and get a pure-Gaussian run for
    # backward compatibility / ablation; stagnation_flags +
    # out_of_envelope are still reported either way.
    disable_regime_dispatch: bool = False
    # Emission driver (schema 0.4.0, issue #6): when True, the box used
    # on stagnation timesteps (regime dispatch, or forced
    # backend="stagnation_box") gets a temperature-led, time-varying
    # E_local(t) instead of the constant Σ-source-rate emission.
    # Default False → exactly the issue-#3 behaviour (back-compatible).
    emission_driver: bool = False
    emission_driver_params: EmissionDriverParams | None = None
    # Stagnation-box overrides (schema 0.5.0): lambda_m enables the
    # receptor-dependent distance kernel; tau_h/area_m2 expose the box
    # constants. None → the v1 lumped box, byte-identical behaviour.
    stagnation_box: StagnationBoxSpec | None = None
    cache_key: str | None = None
    notes: str | None = None


class ForwardRunResult(BaseModel):
    """Result envelope (small results inline; large results referenced)."""

    schema_version: str = SCHEMA_VERSION
    backend: str
    n_times: int
    n_receptors: int
    n_sources: int
    units: str
    receptor_names: list[str]
    timestamps: list[str]
    # 2-D concentration array: [n_times][n_receptors]
    # OR if per_source: 3-D [n_times][n_receptors][n_sources]
    concentrations: list[Any]  # nested list (JSON-friendly)
    summary: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    runtime_ms: int = 0
    # --- stagnation guardrail (schema 0.2.0; additive, backward-compatible) ---
    # Per-timestep flag: True where the hour is calm-nocturnal stagnation,
    # a regime in which the Gaussian-plume backends have ~no skill. Callers
    # should treat flagged timesteps as out-of-envelope, not as confident
    # low concentrations. Defaults to empty so pre-0.2.0 cached payloads
    # still parse.
    stagnation_flags: list[bool] = Field(default_factory=list)
    # Convenience: True if any timestep is stagnation.
    out_of_envelope: bool = False


class InversionRequest(BaseModel):
    """Request for an NNLS emission inversion given observations + footprints."""

    schema_version: str = SCHEMA_VERSION
    sources: list[SourceSpec]  # candidate sources (rates ignored)
    receptors: list[ReceptorSpec]
    meteorology: list[MetSpec]
    observations: list[list[float | None]]  # [n_times][n_receptors]
    l1_lambda: float = 0.0
    smoothness_lambda: float = 0.0


class InversionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    fitted_rates_g_s: list[float]  # [n_sources]
    source_names: list[str]
    residual_rms: float
    fit_diagnostics: dict[str, Any]
