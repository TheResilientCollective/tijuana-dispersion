"""
Pydantic schemas defining the dispersion service API contract.

These are the structures Claude (or any client) sends as JSON to
request a run. Versioned so the contract can evolve without breaking
old clients.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.2.0"


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


class ForwardRunRequest(BaseModel):
    """Request for a forward dispersion run."""

    schema_version: str = SCHEMA_VERSION
    backend: Literal["gaussian_plume", "hysplit"] = "gaussian_plume"
    sources: list[SourceSpec]
    receptors: list[ReceptorSpec]
    meteorology: list[MetSpec]
    units: Literal["ppb", "ugm3"] = "ppb"
    return_per_source: bool = False
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
