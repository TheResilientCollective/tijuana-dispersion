"""Tests for the Lagrangian puff backend (service issue #1).

Acceptance criteria from docs/issues/puff_backend.md:
  - correct output shape;
  - steady wind + single source: agrees with the Gaussian plume to
    within 10% at receptors > 200 m downwind (the puff model
    approaches the plume in steady state);
  - step-change emission (0 → 1 g/s at t=12 h): delayed-then-rising
    signal downwind (the plume model would step instantly);
  - upwind receptor ≈ 0;
  - bounded runtime/memory (loose smoke guard here; the full
    72 h × 38 × 3 Railway budget is an integration concern).

Tests-first per AGENTS.md.
"""

from __future__ import annotations

import time

import numpy as np

from tijuana_dispersion import (
    LagrangianPuffBackend,
    LocalGaussianPlumeBackend,
    MetCondition,
    Receptor,
    Source,
)

# A source near the Tijuana river; receptors due downwind of it.
SRC = Source(name="drain", lat=32.5400, lon=-117.0580, emission_rate_g_s=1.0, height_m=1.0)


def _const_met(n: int, *, wind: float = 3.0, direction: float = 270.0) -> list[MetCondition]:
    """n hours of steady wind. direction is the meteorological 'from'
    bearing; 270° = wind FROM the west → blowing toward the east."""
    return [
        MetCondition(
            timestamp=f"2026-05-10T{h % 24:02d}:00:00-07:00",
            wind_speed_ms=wind,
            wind_direction_deg=direction,
            temperature_c=20.0,
            cloud_cover_frac=0.5,
            is_night=False,
        )
        for h in range(n)
    ]


def _east_receptor(meters: float) -> Receptor:
    """A receptor `meters` east of SRC (≈ downwind for a 270° wind)."""
    dlon = meters / (111_320.0 * np.cos(np.radians(SRC.lat)))
    return Receptor(name=f"E{int(meters)}", lat=SRC.lat, lon=SRC.lon + dlon)


def _west_receptor(meters: float) -> Receptor:
    dlon = meters / (111_320.0 * np.cos(np.radians(SRC.lat)))
    return Receptor(name=f"W{int(meters)}", lat=SRC.lat, lon=SRC.lon - dlon)


# ---------- contract ---------- #


def test_info_is_implemented() -> None:
    b = LagrangianPuffBackend()
    assert b.info.name == "puff"
    assert b.info.version != "0.0.0"
    assert "not yet implemented" not in b.info.notes.lower()


def test_empty_inputs_return_zeros() -> None:
    b = LagrangianPuffBackend()
    met = _const_met(4)
    assert b.run_forward([], [_east_receptor(300.0)], met).shape == (4, 1)
    assert np.all(b.run_forward([], [_east_receptor(300.0)], met) == 0.0)
    assert b.run_forward([SRC], [], met).shape == (4, 0)
    assert b.run_forward([SRC], [_east_receptor(300.0)], []).shape == (0, 1)


def test_malformed_timestamps_fall_back_to_hourly() -> None:
    """Unparseable timestamps must not crash — Δt degrades to 3600 s."""
    b = LagrangianPuffBackend()
    bad = [
        MetCondition(
            timestamp="not-a-timestamp",
            wind_speed_ms=3.0,
            wind_direction_deg=270.0,
            temperature_c=20.0,
            cloud_cover_frac=0.5,
            is_night=False,
        )
        for _ in range(5)
    ]
    arr = b.run_forward([SRC], [_east_receptor(500.0)], bad, units="ugm3")
    assert arr.shape == (5, 1)
    assert np.all(np.isfinite(arr))
    assert np.all(arr >= 0.0)


def test_run_forward_shape_and_nonnegative() -> None:
    b = LagrangianPuffBackend()
    recs = [_east_receptor(300.0), _east_receptor(800.0)]
    met = _const_met(6)
    arr = b.run_forward([SRC], recs, met, units="ppb")
    assert arr.shape == (6, 2)
    assert np.all(arr >= 0.0)
    assert np.all(np.isfinite(arr))


def test_per_source_shape() -> None:
    b = LagrangianPuffBackend()
    srcs = [SRC, Source(name="s2", lat=32.541, lon=-117.058, emission_rate_g_s=0.5)]
    recs = [_east_receptor(400.0)]
    arr = b.run_forward_per_source(srcs, recs, _const_met(5), units="ugm3")
    assert arr.shape == (5, 1, 2)
    assert np.all(arr >= 0.0)


# ---------- physics ---------- #


def test_upwind_receptor_is_near_zero() -> None:
    """Wind FROM west (270°): a receptor west of the source is upwind."""
    b = LagrangianPuffBackend()
    rec = _west_receptor(500.0)
    arr = b.run_forward([SRC], [rec], _const_met(8), units="ugm3")
    # Many orders of magnitude below a typical downwind value.
    down = b.run_forward([SRC], [_east_receptor(500.0)], _const_met(8), units="ugm3")
    assert arr[-1, 0] < 0.01 * down[-1, 0]


def test_steady_state_agrees_with_plume_within_10pct() -> None:
    """The defining acceptance test: in steady wind the puff sum
    approaches the steady-state Gaussian plume at receptors
    > 200 m downwind."""
    puff = LagrangianPuffBackend()
    plume = LocalGaussianPlumeBackend()
    recs = [_east_receptor(300.0), _east_receptor(600.0), _east_receptor(1200.0)]
    met = _const_met(10)  # long enough to reach steady state
    cp = puff.run_forward([SRC], recs, met, units="ugm3")[-1]
    cg = plume.run_forward([SRC], recs, met, units="ugm3")[-1]
    for r in range(len(recs)):
        assert cg[r] > 0.0
        rel = abs(cp[r] - cg[r]) / cg[r]
        assert rel < 0.10, (
            f"receptor {recs[r].name}: puff {cp[r]:.4g} vs plume {cg[r]:.4g} ({rel:.1%})"
        )


def test_step_change_emission_is_delayed_then_rising() -> None:
    """Turn-on transient. With a cold puff field and emission starting
    at t=0, a receptor 900 m downwind must show a *delayed-then-rising*
    signal: ~0 at the first hour (transport + fill-in delay), rising
    toward a steady value over the next hours. A steady-state plume
    CANNOT show this — it is instantaneous from hour 0. (Equivalent to
    the doc's 0→1 g/s step: the post-turn-on transient is exactly the
    cold-start transient.)"""
    puff = LagrangianPuffBackend()
    plume = LocalGaussianPlumeBackend()
    # Far receptor + slow wind so transport time (~1.7 h) exceeds the
    # 1 h step — the plume needs multiple hours to fill in, exposing
    # the cross-hour transient. (At 900 m / 3 m/s transport is 300 s
    # ≪ 1 h, so the puff is already steady by hour 0 — no delay to see.)
    rec = [_east_receptor(12_000.0)]
    met = _const_met(12, wind=2.0)
    src_on = [Source(name="d", lat=SRC.lat, lon=SRC.lon, emission_rate_g_s=1.0)]
    src_off = [Source(name="d", lat=SRC.lat, lon=SRC.lon, emission_rate_g_s=0.0)]

    # Zero emission → identically zero everywhere (the 0→ off phase).
    off_phase = puff.run_forward(src_off, rec, met[:6], units="ugm3")
    assert np.allclose(off_phase, 0.0)

    # Cold start at t=0 → delayed (plume not yet arrived), then rising.
    on = puff.run_forward(src_on, rec, met, units="ugm3")[:, 0]
    assert on[0] < 0.5 * on[-1]  # delayed: first hour well below steady
    assert on[-1] > on[0]  # then rising
    assert np.all(np.diff(on[:5]) >= -1e-9)  # monotone non-decreasing early

    # Plume reference: instantaneous steady state from hour 0.
    pg = plume.run_forward(src_on, rec, met, units="ugm3")[:, 0]
    assert pg[0] > 0.0
    assert abs(pg[0] - pg[-1]) / pg[-1] < 0.05


def test_runtime_smoke_guard() -> None:
    """Loose perf guard (full Railway budget is an integration test):
    24 h × 5 sources × 3 receptors well under a few seconds locally."""
    b = LagrangianPuffBackend()
    srcs = [
        Source(name=f"s{i}", lat=SRC.lat + 0.001 * i, lon=SRC.lon, emission_rate_g_s=1.0)
        for i in range(5)
    ]
    recs = [_east_receptor(300.0), _east_receptor(700.0), _east_receptor(1500.0)]
    t0 = time.time()
    arr = b.run_forward(srcs, recs, _const_met(24), units="ppb")
    assert arr.shape == (24, 3)
    assert time.time() - t0 < 8.0
