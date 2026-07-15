"""Tests for the tide-ebb culvert enhancement (Saturn Blvd mechanism).

f_ebb = 1 + a_ebb * max(0, -d(tide)/dt): inert on rising/slack water and
whenever a_ebb == 0; applied only to sources named in ebb_source_names.
"""

from __future__ import annotations

import pytest

from tijuana_dispersion import EmissionParameters, EmissionsModel, f_flow_turbulence, f_tide_ebb
from tijuana_dispersion.emissions import EmissionDrivers, SourceSpecLocation


def _driver(tide_rate: float, border_flow: float | None = None) -> EmissionDrivers:
    return EmissionDrivers(
        timestamp="2026-03-14T03:00:00-08:00",
        temperature_c=15.0,
        wind_speed_10m_ms=1.0,
        sbiwtp_flow_mgd=25.0,
        sbiwtp_deficit=0.0,
        tide_height_m=0.5,
        is_night=True,
        tide_rate_m_h=tide_rate,
        border_flow_m3s=border_flow,
    )


def test_f_tide_ebb_only_on_falling_tide() -> None:
    params = EmissionParameters(a_ebb=2.0)
    assert f_tide_ebb(_driver(+0.3), params) == pytest.approx(1.0)  # flood
    assert f_tide_ebb(_driver(0.0), params) == pytest.approx(1.0)  # slack
    assert f_tide_ebb(_driver(-0.3), params) == pytest.approx(1.6)  # ebb
    # a_ebb=0 disables regardless of tide.
    assert f_tide_ebb(_driver(-0.3), EmissionParameters()) == pytest.approx(1.0)


def test_ebb_applies_only_to_named_sources() -> None:
    params = EmissionParameters(
        a_ebb=2.0,
        ebb_source_names=("Saturn Blvd Bridge",),
        baselines_g_s={"Saturn Blvd Bridge": 1.0, "Dairy Mart Bridge": 1.0},
    )
    model = EmissionsModel(params)
    saturn = SourceSpecLocation(
        name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, archetype="channel"
    )
    dairy = SourceSpecLocation(
        name="Dairy Mart Bridge", lat=32.5485, lon=-117.0643, archetype="channel"
    )
    ebb, flood = _driver(-0.3), _driver(+0.3)
    # Same source, ebb vs flood: exactly the f_ebb factor.
    assert model.emission_rate_g_s(saturn, ebb) == pytest.approx(
        1.6 * model.emission_rate_g_s(saturn, flood)
    )
    # Un-named source: no tide response.
    assert model.emission_rate_g_s(dairy, ebb) == pytest.approx(
        model.emission_rate_g_s(dairy, flood)
    )


def test_default_drivers_are_ebb_inert() -> None:
    """tide_rate_m_h defaults to 0.0 — pre-existing driver construction
    (from_dataframe_row, MCMC paths) sees no behaviour change."""
    params = EmissionParameters(a_ebb=5.0, ebb_source_names=("x",))
    d = EmissionDrivers(
        timestamp="t",
        temperature_c=15.0,
        wind_speed_10m_ms=1.0,
        sbiwtp_flow_mgd=25.0,
        sbiwtp_deficit=0.0,
        tide_height_m=0.5,
        is_night=True,
    )
    assert f_tide_ebb(d, params) == pytest.approx(1.0)


def test_f_flow_turbulence_scales_above_threshold() -> None:
    params = EmissionParameters(a_flow=2.0, flow_threshold_m3s=0.44)
    # No flow data -> inert; below threshold -> inert; above -> linear.
    assert f_flow_turbulence(_driver(0.0), params) == pytest.approx(1.0)
    assert f_flow_turbulence(_driver(0.0, border_flow=0.2), params) == pytest.approx(1.0)
    assert f_flow_turbulence(_driver(0.0, border_flow=2.44), params) == pytest.approx(5.0)
    # a_flow=0 disables regardless of flow.
    assert f_flow_turbulence(_driver(0.0, border_flow=2.44), EmissionParameters()) == pytest.approx(
        1.0
    )


def test_flow_and_ebb_compose_on_hotspot_sources() -> None:
    params = EmissionParameters(
        a_ebb=2.0,
        a_flow=1.0,
        flow_threshold_m3s=0.44,
        ebb_source_names=("Saturn Blvd Bridge",),
        baselines_g_s={"Saturn Blvd Bridge": 1.0, "Dairy Mart Bridge": 1.0},
    )
    model = EmissionsModel(params)
    saturn = SourceSpecLocation(
        name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, archetype="channel"
    )
    dairy = SourceSpecLocation(
        name="Dairy Mart Bridge", lat=32.5485, lon=-117.0643, archetype="channel"
    )
    quiet = _driver(+0.3, border_flow=0.44)  # flood tide, at-threshold flow
    active = _driver(-0.3, border_flow=1.44)  # ebb + 1 m3/s above threshold
    # Composition: f_ebb(1.6) * f_flow(2.0) = 3.2x on the hotspot source.
    assert model.emission_rate_g_s(saturn, active) == pytest.approx(
        3.2 * model.emission_rate_g_s(saturn, quiet)
    )
    # Non-hotspot source: unaffected by either term.
    assert model.emission_rate_g_s(dairy, active) == pytest.approx(
        model.emission_rate_g_s(dairy, quiet)
    )
