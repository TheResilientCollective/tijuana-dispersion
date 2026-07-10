"""
Tests for tijuana_dispersion.core.

The rules in AGENTS.md require analytical-limit tests for core.py
(zero concentration upwind, plume-axis maximum at downwind centerline,
σ_y monotonic in distance). Those are the tests here.

Coverage target: 80% on this module. Trivial tests don't count toward
the goal — these are physics tests against analytical expectations.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tijuana_dispersion import (
    MetCondition,
    Receptor,
    Source,
    forward_run,
    forward_run_per_source,
    gaussian_plume_concentration,
    pasquill_stability,
    ugm3_to_ppb_h2s,
)
from tijuana_dispersion.core import briggs_sigma

# ============================================================
# Pasquill stability classification
# ============================================================


def test_pasquill_calm_clear_night_is_F() -> None:
    """Very stable conditions: calm wind, clear sky, night."""
    assert pasquill_stability(0.5, is_night=True, cloud_cover_frac=0.1) == "F"


def test_pasquill_breezy_overcast_night_is_D() -> None:
    """Neutral conditions: moderate wind, cloudy, night."""
    assert pasquill_stability(5.0, is_night=True, cloud_cover_frac=0.8) == "D"


def test_pasquill_calm_day_is_unstable() -> None:
    """Unstable daytime conditions."""
    cls = pasquill_stability(1.5, is_night=False, cloud_cover_frac=0.3)
    assert cls in ("A", "B")


# ============================================================
# Briggs σ coefficients
# ============================================================


def test_briggs_sigma_monotonic_in_distance() -> None:
    """σ_y and σ_z should both increase with downwind distance."""
    distances = np.array([100.0, 500.0, 1000.0, 2000.0, 5000.0])
    for stab in ["A", "B", "C", "D", "E", "F"]:
        sy, sz = briggs_sigma(stab, distances)
        assert np.all(np.diff(sy) > 0), f"σ_y not monotonic for class {stab}"
        assert np.all(np.diff(sz) > 0), f"σ_z not monotonic for class {stab}"


def test_briggs_sigma_more_stable_means_smaller_dispersion() -> None:
    """Stable conditions (F) should have smaller σ than unstable (B) at same distance."""
    distance = np.array([1000.0])
    sy_b, sz_b = briggs_sigma("B", distance)
    sy_f, sz_f = briggs_sigma("F", distance)
    assert sy_f[0] < sy_b[0]
    assert sz_f[0] < sz_b[0]


# ============================================================
# Gaussian plume — analytical limits
# ============================================================


def test_concentration_zero_upwind(
    stewarts_source: Source,
    nestor_receptor: Receptor,
) -> None:
    """A receptor upwind of the source should see zero concentration."""
    # NESTOR is NW of Stewart's. Wind FROM NW means wind blows SE,
    # which puts NESTOR upwind of Stewart's.
    met_nw = MetCondition(
        timestamp="2026-03-14T03:00:00-08:00",
        wind_speed_ms=2.0,
        wind_direction_deg=315.0,  # from NW
        temperature_c=15.0,
        cloud_cover_frac=0.3,
        is_night=True,
    )
    c = gaussian_plume_concentration(stewarts_source, nestor_receptor, met_nw)
    assert c == 0.0


def test_concentration_nonzero_downwind(
    stewarts_source: Source,
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
) -> None:
    """SE wind carries Stewart's plume to NESTOR (which is NW of Stewart's)."""
    c = gaussian_plume_concentration(stewarts_source, nestor_receptor, calm_night_met)
    assert c > 0.0


def test_concentration_higher_when_stable(
    stewarts_source: Source,
    nestor_receptor: Receptor,
) -> None:
    """Stable nocturnal conditions should produce higher concentrations than
    breezy daytime conditions for the same source and receptor geometry."""
    met_calm = MetCondition(
        timestamp="2026-03-14T03:00:00-08:00",
        wind_speed_ms=1.5,
        wind_direction_deg=135.0,  # from SE
        temperature_c=15.0,
        cloud_cover_frac=0.2,
        is_night=True,
    )
    met_windy = MetCondition(
        timestamp="2026-03-14T14:00:00-08:00",
        wind_speed_ms=5.0,
        wind_direction_deg=135.0,  # same direction
        temperature_c=20.0,
        cloud_cover_frac=0.3,
        is_night=False,
    )
    c_calm = gaussian_plume_concentration(stewarts_source, nestor_receptor, met_calm)
    c_windy = gaussian_plume_concentration(stewarts_source, nestor_receptor, met_windy)
    assert c_calm > c_windy


def test_concentration_linear_in_emission_rate(
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
) -> None:
    """Concentration should scale linearly with emission rate (Gaussian plume is linear)."""
    src1 = Source(
        name="x",
        lat=32.54064,
        lon=-117.05801,
        emission_rate_g_s=1.0,
        archetype="drain",
    )
    src10 = Source(
        name="x",
        lat=32.54064,
        lon=-117.05801,
        emission_rate_g_s=10.0,
        archetype="drain",
    )
    c1 = gaussian_plume_concentration(src1, nestor_receptor, calm_night_met)
    c10 = gaussian_plume_concentration(src10, nestor_receptor, calm_night_met)
    assert c10 == pytest.approx(10 * c1)


def test_concentration_inverse_in_wind_speed_at_high_wind(
    stewarts_source: Source,
    nestor_receptor: Receptor,
) -> None:
    """For fixed stability class, concentration ∝ 1/u (Gaussian plume formula).

    Both test cases use ≥6 m/s daytime winds with heavy cloud, which Pasquill
    pins to class D (neutral) — so σy and σz don't shift between cases and
    the only u-dependence is the explicit 1/u in the plume formula.
    """
    met_8 = MetCondition(
        timestamp="2026-03-14T14:00:00-08:00",
        wind_speed_ms=8.0,
        wind_direction_deg=135.0,
        temperature_c=15.0,
        cloud_cover_frac=0.8,
        is_night=False,
    )
    met_16 = MetCondition(
        timestamp="2026-03-14T14:00:00-08:00",
        wind_speed_ms=16.0,
        wind_direction_deg=135.0,
        temperature_c=15.0,
        cloud_cover_frac=0.8,
        is_night=False,
    )
    c_8 = gaussian_plume_concentration(stewarts_source, nestor_receptor, met_8)
    c_16 = gaussian_plume_concentration(stewarts_source, nestor_receptor, met_16)
    # Both winds are in class D, so the ratio is exactly u_16 / u_8 = 2.
    assert c_8 / c_16 == pytest.approx(2.0, rel=0.05)


# ============================================================
# Unit conversion
# ============================================================


def test_h2s_ugm3_to_ppb_at_25c() -> None:
    """At 25°C, 1.39 µg/m³ ≈ 1 ppb for H₂S (MW 34.08)."""
    ppb = ugm3_to_ppb_h2s(1.39, temp_c=25.0)
    assert ppb == pytest.approx(1.0, rel=0.01)


def test_h2s_ugm3_to_ppb_temperature_dependence() -> None:
    """Cold air is denser, so same mass concentration → fewer ppb (smaller molar volume)."""
    ppb_cold = ugm3_to_ppb_h2s(1.0, temp_c=5.0)
    ppb_warm = ugm3_to_ppb_h2s(1.0, temp_c=35.0)
    assert ppb_cold < ppb_warm


# ============================================================
# Vectorized forward_run
# ============================================================


def test_forward_run_shape(
    stewarts_source: Source,
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
    windy_day_met: MetCondition,
) -> None:
    """Output array shape should be (n_times, n_receptors)."""
    result = forward_run(
        sources=[stewarts_source, stewarts_source],
        receptors=[nestor_receptor],
        met_series=[calm_night_met, windy_day_met, calm_night_met],
        units="ppb",
    )
    assert result.shape == (3, 1)


def test_forward_run_sums_over_sources(
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
) -> None:
    """forward_run with N identical sources should give N× the single-source result."""
    src = Source(name="x", lat=32.54064, lon=-117.05801, emission_rate_g_s=1.0, archetype="drain")
    one = forward_run([src], [nestor_receptor], [calm_night_met], units="ppb")
    five = forward_run([src] * 5, [nestor_receptor], [calm_night_met], units="ppb")
    assert five[0, 0] == pytest.approx(5 * one[0, 0])


# ============================================================
# Stability table — fill in classes not exercised above
# ============================================================


def test_pasquill_stable_clear_night_E_F_branches() -> None:
    """Clear-sky nighttime spans F (very stable, calm) through D (neutral, breezy)."""
    assert pasquill_stability(1.0, is_night=True, cloud_cover_frac=0.1) == "F"
    assert pasquill_stability(2.5, is_night=True, cloud_cover_frac=0.1) == "E"
    assert pasquill_stability(4.0, is_night=True, cloud_cover_frac=0.1) == "D"
    assert pasquill_stability(7.0, is_night=True, cloud_cover_frac=0.1) == "D"


def test_pasquill_overcast_night_E_D_branches() -> None:
    """Overcast nighttime is less stable than clear: E at calm, D otherwise."""
    assert pasquill_stability(1.0, is_night=True, cloud_cover_frac=0.9) == "E"
    assert pasquill_stability(3.0, is_night=True, cloud_cover_frac=0.9) == "D"


def test_pasquill_daytime_spans_B_C_D() -> None:
    """Daytime moves from B (light wind) to D (strong wind)."""
    assert pasquill_stability(1.5, is_night=False, cloud_cover_frac=0.3) == "B"
    assert pasquill_stability(4.0, is_night=False, cloud_cover_frac=0.3) == "C"
    assert pasquill_stability(7.0, is_night=False, cloud_cover_frac=0.3) == "D"


# ============================================================
# forward_run µg/m³ branch + per-source variant
# ============================================================


def test_forward_run_units_ugm3(
    stewarts_source: Source,
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
) -> None:
    """The 'ugm3' branch skips the H2S ppb conversion."""
    ugm3 = forward_run([stewarts_source], [nestor_receptor], [calm_night_met], units="ugm3")
    ppb = forward_run([stewarts_source], [nestor_receptor], [calm_night_met], units="ppb")
    # The ppb value is ugm3_to_ppb_h2s(ugm3, temperature_c). At 14°C they differ.
    assert ugm3.shape == ppb.shape
    expected = ugm3_to_ppb_h2s(float(ugm3[0, 0]), calm_night_met.temperature_c)
    assert ppb[0, 0] == pytest.approx(expected, rel=1e-6)


def test_forward_run_per_source_separates_contributions(
    nestor_receptor: Receptor,
    calm_night_met: MetCondition,
) -> None:
    """Per-source array should sum across the source axis to forward_run."""
    src_a = Source(name="a", lat=32.54064, lon=-117.05801, emission_rate_g_s=1.0, archetype="drain")
    src_b = Source(name="b", lat=32.54300, lon=-117.06000, emission_rate_g_s=2.0, archetype="drain")
    per_source = forward_run_per_source(
        [src_a, src_b], [nestor_receptor], [calm_night_met], units="ugm3"
    )
    total = forward_run([src_a, src_b], [nestor_receptor], [calm_night_met], units="ugm3")
    assert per_source.shape == (1, 1, 2)
    assert total[0, 0] == pytest.approx(per_source[0, 0, :].sum(), rel=1e-6)


# ============================================================
# Mixing lid (nocturnal boundary-layer trapping) — issue: mixing-height
# ============================================================


def _lidded(met: MetCondition, L: float | None) -> MetCondition:
    return dataclasses.replace(met, mixing_height_m=L)


def test_lid_none_matches_unbounded(
    stewarts_source: Source, nestor_receptor: Receptor, calm_night_met: MetCondition
) -> None:
    """mixing_height_m=None reproduces the original unbounded plume exactly."""
    base = gaussian_plume_concentration(stewarts_source, nestor_receptor, calm_night_met)
    c = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, None)
    )
    assert c == base


def test_high_lid_approximates_unbounded(
    stewarts_source: Source, nestor_receptor: Receptor, calm_night_met: MetCondition
) -> None:
    """A very high lid is not felt by the plume -> ~unbounded."""
    base = gaussian_plume_concentration(stewarts_source, nestor_receptor, calm_night_met)
    c = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, 100_000.0)
    )
    assert c == pytest.approx(base, rel=1e-6)


def test_shallow_lid_enhances_ground_concentration(
    stewarts_source: Source, nestor_receptor: Receptor, calm_night_met: MetCondition
) -> None:
    """A shallow nocturnal lid traps the plume -> higher ground concentration."""
    base = gaussian_plume_concentration(stewarts_source, nestor_receptor, calm_night_met)
    c = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, 50.0)
    )
    assert c > base


def test_lower_lid_more_enhancement(
    stewarts_source: Source, nestor_receptor: Receptor, calm_night_met: MetCondition
) -> None:
    """Ground concentration increases monotonically as the lid lowers."""
    c_hi = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, 400.0)
    )
    c_mid = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, 100.0)
    )
    c_lo = gaussian_plume_concentration(
        stewarts_source, nestor_receptor, _lidded(calm_night_met, 40.0)
    )
    assert c_lo > c_mid > c_hi


def test_wellmixed_limit_matches_reflection_at_crossover() -> None:
    """Reflection sum and well-mixed formula agree at the σz≈1.6·L crossover
    (continuity of the two regimes)."""

    # A geometry/met where we can read σz and place L right at the crossover.
    src = Source(name="s", lat=32.5406, lon=-117.0580, emission_rate_g_s=1.0, archetype="drain")
    rec = Receptor(name="r", lat=32.5480, lon=-117.0660, height_m=0.0)
    met = MetCondition(
        timestamp="2026-03-14T03:00:00-08:00",
        wind_speed_ms=1.5,
        wind_direction_deg=135.0,
        temperature_c=15.0,
        cloud_cover_frac=0.2,
        is_night=True,
    )
    # Just below vs just above the crossover should be within a few %.
    c_below = gaussian_plume_concentration(src, rec, _lidded(met, 200.0))  # reflection or mixed
    c_above = gaussian_plume_concentration(src, rec, _lidded(met, 199.0))
    assert c_above == pytest.approx(c_below, rel=0.05)
