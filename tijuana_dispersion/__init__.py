"""Tijuana River Valley H2S dispersion service."""

from .backends import (
    Backend,
    BackendInfo,
    EnsembleBackend,
    EnsembleMember,
    LagrangianPuffBackend,
    LocalGaussianPlumeBackend,
    RemoteHTTPBackend,
    StagnationBoxBackend,
    build_default_ensemble,
)
from .calibration import (
    ARCHETYPE_BOUNDS_G_S,
    ARCHETYPE_PRIOR_G_S,
    BoundedInversionResult,
    distributed_area_sources,
    distributed_channel_sources,
    run_inversion_bounded,
    wind_conditional_residuals,
)
from .core import (
    MetCondition,
    Receptor,
    Source,
    forward_run,
    forward_run_per_source,
    gaussian_plume_concentration,
    pasquill_stability,
    ugm3_to_ppb_h2s,
)
from .emissions import (
    EmissionDrivers,
    EmissionParameters,
    EmissionsModel,
    SourceSpecLocation,
    f_diel,
    f_flow_turbulence,
    f_substrate,
    f_temperature,
    f_tide_ebb,
    f_volatilization,
    make_emissions_model_with_overrides,
)
from .regime import DEFAULT_U_CALM_MS, is_stagnation
from .schemas import (
    SCHEMA_VERSION,
    EmissionDriverParams,
    ForwardRunRequest,
    ForwardRunResult,
    InversionRequest,
    InversionResult,
    MetSpec,
    ReceptorSpec,
    SourceSpec,
    StagnationBoxSpec,
)
from .service import run_forward, run_inversion
from .stagnation import (
    H_MIX_BY_STABILITY_M,
    StagnationBoxParams,
    TemperatureEmissionParams,
    box_series,
    distance_weighted_e_local,
    drainage_weighted_e_local,
    temperature_led_e_local,
)

__version__ = "0.4.0"
# Grouped by submodule for readability; intentional ordering.
__all__ = [  # noqa: RUF022
    # core
    "Source",
    "Receptor",
    "MetCondition",
    "forward_run",
    "forward_run_per_source",
    "gaussian_plume_concentration",
    "pasquill_stability",
    "ugm3_to_ppb_h2s",
    # schemas
    "SourceSpec",
    "ReceptorSpec",
    "MetSpec",
    "ForwardRunRequest",
    "ForwardRunResult",
    "InversionRequest",
    "InversionResult",
    "EmissionDriverParams",
    # service
    "run_forward",
    "run_inversion",
    # regime (stagnation guardrail)
    "is_stagnation",
    "DEFAULT_U_CALM_MS",
    # stagnation box (issue #3) + emission driver (issue #6)
    "StagnationBoxParams",
    "StagnationBoxSpec",
    "distance_weighted_e_local",
    "drainage_weighted_e_local",
    "box_series",
    "H_MIX_BY_STABILITY_M",
    "TemperatureEmissionParams",
    "temperature_led_e_local",
    # calibration
    "distributed_channel_sources",
    "distributed_area_sources",
    "run_inversion_bounded",
    "wind_conditional_residuals",
    "ARCHETYPE_BOUNDS_G_S",
    "ARCHETYPE_PRIOR_G_S",
    "BoundedInversionResult",
    # backends
    "Backend",
    "BackendInfo",
    "LocalGaussianPlumeBackend",
    "LagrangianPuffBackend",
    "StagnationBoxBackend",
    "RemoteHTTPBackend",
    "EnsembleBackend",
    "EnsembleMember",
    "build_default_ensemble",
    # emissions
    "EmissionDrivers",
    "EmissionParameters",
    "EmissionsModel",
    "SourceSpecLocation",
    "f_flow_turbulence",
    "f_temperature",
    "f_tide_ebb",
    "f_substrate",
    "f_volatilization",
    "f_diel",
    "make_emissions_model_with_overrides",
    # version
    "SCHEMA_VERSION",
]
