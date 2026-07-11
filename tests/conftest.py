"""Shared pytest fixtures for the dispersion service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tijuana_dispersion import MetCondition, Receptor, Source, service


@pytest.fixture(autouse=True)
def _isolated_forward_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the run_forward request cache at a per-test directory.

    The cache is keyed on the request hash only — physics changes that
    don't alter the request (monkeypatched internals, code edits between
    runs) would otherwise serve stale results across tests.
    """
    cache = tmp_path / "forward_cache"
    cache.mkdir()
    monkeypatch.setattr(service, "CACHE_DIR", cache)


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
