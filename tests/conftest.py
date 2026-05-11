"""Shared pytest fixtures for the dispersion service tests."""

from __future__ import annotations

import pytest

from tijuana_dispersion import MetCondition, Receptor, Source


@pytest.fixture
def stewarts_source() -> Source:
    """Stewart's Drain — the most-studied named source."""
    return Source(
        name="Stewart's Drain",
        lat=32.54064,
        lon=-117.05801,
        emission_rate_g_s=1.0,
        height_m=1.0,
        archetype="drain",
    )


@pytest.fixture
def nestor_receptor() -> Receptor:
    """NESTOR-BES monitoring station."""
    return Receptor(
        name="NESTOR - BES",
        lat=32.567097,
        lon=-117.090656,
        height_m=2.0,
    )


@pytest.fixture
def calm_night_met() -> MetCondition:
    """Typical conditions during nocturnal H₂S exceedances: calm SE wind, cool, dry."""
    return MetCondition(
        timestamp="2026-03-14T03:00:00-08:00",
        wind_speed_ms=1.5,
        wind_direction_deg=135.0,  # from SE
        temperature_c=14.0,
        cloud_cover_frac=0.2,
        is_night=True,
    )


@pytest.fixture
def windy_day_met() -> MetCondition:
    """Daytime breezy conditions: westerly wind, warm, moderately cloudy."""
    return MetCondition(
        timestamp="2026-03-14T14:00:00-08:00",
        wind_speed_ms=4.0,
        wind_direction_deg=270.0,  # from W
        temperature_c=20.0,
        cloud_cover_frac=0.3,
        is_night=False,
    )
