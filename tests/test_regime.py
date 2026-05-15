"""Tests for the stagnation regime classifier and its wiring into the
forward result (issue #2 — calm-nocturnal guardrail).

The guardrail exists because the Gaussian-plume backends have ~zero
skill in the calm-nocturnal stagnation regime; the service must flag
those hours rather than present a confident low concentration.
"""

from __future__ import annotations

from tijuana_dispersion import (
    ForwardRunRequest,
    ForwardRunResult,
    MetCondition,
    MetSpec,
    ReceptorSpec,
    SourceSpec,
    is_stagnation,
    run_forward,
)
from tijuana_dispersion.regime import DEFAULT_U_CALM_MS
from tijuana_dispersion.schemas import SCHEMA_VERSION


def _met(wind_speed_ms: float, is_night: bool) -> MetCondition:
    return MetCondition(
        timestamp="2026-05-10T23:00:00-07:00",
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=300.0,
        temperature_c=15.0,
        cloud_cover_frac=0.2,
        is_night=is_night,
    )


# ---------- classifier ---------- #


def test_calm_night_is_stagnation(calm_night_met: MetCondition) -> None:
    """Night + wind below the calm threshold → stagnation."""
    assert is_stagnation(calm_night_met) is True


def test_windy_day_is_not_stagnation(windy_day_met: MetCondition) -> None:
    """Daytime breezy conditions → advective, not stagnation."""
    assert is_stagnation(windy_day_met) is False


def test_windy_night_is_not_stagnation() -> None:
    """Night but well-ventilated → not stagnation (advective)."""
    assert is_stagnation(_met(6.0, is_night=True)) is False


def test_calm_day_is_not_stagnation() -> None:
    """Calm but daytime → not stagnation (must be nocturnal)."""
    assert is_stagnation(_met(0.5, is_night=False)) is False


def test_boundary_is_strict_less_than() -> None:
    """wind == u_calm is NOT stagnation; just below IS."""
    assert is_stagnation(_met(DEFAULT_U_CALM_MS, is_night=True)) is False
    assert is_stagnation(_met(DEFAULT_U_CALM_MS - 0.01, is_night=True)) is True


def test_custom_u_calm_threshold_is_respected() -> None:
    m = _met(3.0, is_night=True)
    assert is_stagnation(m, u_calm=2.5) is False
    assert is_stagnation(m, u_calm=3.5) is True


# ---------- schema additions ---------- #


def test_schema_version_bumped_for_additive_change() -> None:
    """The contract gained additive fields → minor version bump."""
    assert SCHEMA_VERSION == "0.2.0"


def test_forward_result_stagnation_fields_default_safe() -> None:
    """Old callers / old cached JSON without the new fields still parse:
    defaults must be a non-flagged, empty state."""
    r = ForwardRunResult(
        backend="gaussian_plume",
        n_times=0,
        n_receptors=0,
        n_sources=0,
        units="ppb",
        receptor_names=[],
        timestamps=[],
        concentrations=[],
    )
    assert r.out_of_envelope is False
    assert r.stagnation_flags == []


# ---------- service wiring ---------- #


def _request(met_specs: list[MetSpec]) -> ForwardRunRequest:
    return ForwardRunRequest(
        backend="gaussian_plume",
        sources=[
            SourceSpec(
                name="Stewart's Drain",
                lat=32.54064,
                lon=-117.05801,
                emission_rate_g_s=1.0,
                archetype="drain",
            )
        ],
        receptors=[ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656)],
        meteorology=met_specs,
        cache_key=None,
    )


def _metspec(ts: str, wind: float, night: bool) -> MetSpec:
    return MetSpec(
        timestamp=ts,
        wind_speed_ms=wind,
        wind_direction_deg=300.0,
        temperature_c=15.0,
        cloud_cover_frac=0.2,
        is_night=night,
    )


def test_run_forward_flags_mixed_series() -> None:
    """A series mixing a calm-night hour and a windy-day hour must flag
    exactly the stagnation hour and set out_of_envelope."""
    req = _request(
        [
            _metspec("2026-05-10T23:00:00-07:00", 1.4, night=True),  # stagnation
            _metspec("2026-05-11T14:00:00-07:00", 5.0, night=False),  # advective
        ]
    )
    res = run_forward(req)
    assert res.stagnation_flags == [True, False]
    assert res.out_of_envelope is True
    assert res.summary["n_stagnation_hours"] == 1
    assert res.summary["regime"] == "stagnation"


def test_run_forward_all_advective_not_flagged() -> None:
    req = _request(
        [
            _metspec("2026-05-11T13:00:00-07:00", 5.0, night=False),
            _metspec("2026-05-11T14:00:00-07:00", 6.0, night=False),
        ]
    )
    res = run_forward(req)
    assert res.stagnation_flags == [False, False]
    assert res.out_of_envelope is False
    assert res.summary["n_stagnation_hours"] == 0
    assert res.summary["regime"] == "advective"
