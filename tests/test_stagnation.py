"""Tests for the stagnation box-accumulation model + regime dispatch
(issue #3).

The Gaussian backends have ~zero skill in the calm-nocturnal regime
(experiments v3→v3.6: "you cannot trap a plume that never arrived").
This covers the box recurrence, the H_mix-by-stability table, the
`StagnationBoxBackend`, and the per-timestep dispatch wired into
`run_forward` (box on stagnation hours, Gaussian otherwise).

Tests are written first per AGENTS.md. The box's *parameter
calibration* against the 242 Berry >100 ppb hours is an
experiments-repo follow-up (no calibration data lives in this repo).
"""

from __future__ import annotations

import numpy as np

from tijuana_dispersion import (
    ForwardRunRequest,
    MetCondition,
    MetSpec,
    Receptor,
    ReceptorSpec,
    Source,
    SourceSpec,
    StagnationBoxBackend,
    run_forward,
)
from tijuana_dispersion.schemas import SCHEMA_VERSION
from tijuana_dispersion.stagnation import (
    H_MIX_BY_STABILITY_M,
    StagnationBoxParams,
    box_series,
)


def _met(ts: str, wind: float, night: bool, temp: float = 15.0) -> MetCondition:
    return MetCondition(
        timestamp=ts,
        wind_speed_ms=wind,
        wind_direction_deg=300.0,
        temperature_c=temp,
        cloud_cover_frac=0.2,
        is_night=night,
    )


# ---------- H_mix table ---------- #


def test_h_mix_monotonic_in_stability() -> None:
    """Shallower mixing for more stable classes: A(deep) … F(shallow)."""
    order = ["A", "B", "C", "D", "E", "F"]
    depths = [H_MIX_BY_STABILITY_M[c] for c in order]
    assert depths == sorted(depths, reverse=True)
    assert H_MIX_BY_STABILITY_M["F"] <= 100.0  # collapsed nocturnal SBL
    assert H_MIX_BY_STABILITY_M["A"] >= 1000.0


# ---------- box recurrence ---------- #


def test_box_accumulates_then_approaches_steady_state() -> None:
    """Under constant calm-night forcing, C rises monotonically toward
    the fixed point E*tau/(A*H_mix)."""
    p = StagnationBoxParams(tau_h=4.0, e_local_g_s=2.0, area_m2=4.0e6)
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.5, night=True) for h in range(20)]
    c = box_series(met, p, units="ugm3")
    assert c.shape == (20,)
    assert np.all(c >= 0.0)
    assert np.all(np.diff(c) > 0.0)  # monotone rise from 0
    # Approaches the analytic fixed point C* = E*tau/(A*H_mix) (µg/m³).
    h_mix = H_MIX_BY_STABILITY_M["F"]  # calm clear night → F
    c_star = (p.e_local_g_s * 1e6) * (p.tau_h * 3600.0) / (p.area_m2 * h_mix)
    assert abs(c[-1] - c_star) / c_star < 0.05


def test_box_decays_when_forcing_stops() -> None:
    """A burst of calm hours then a (still-calm) low-emission tail decays."""
    p = StagnationBoxParams(tau_h=2.0, e_local_g_s=3.0, area_m2=4.0e6)
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.0, night=True) for h in range(8)]
    c = box_series(met, p, units="ugm3")
    p0 = StagnationBoxParams(tau_h=2.0, e_local_g_s=0.0, area_m2=4.0e6)
    tail = box_series(met, p0, units="ugm3", c_init=float(c[-1]))
    assert np.all(np.diff(tail) < 0.0)  # decays toward 0 with no source


def test_box_ppb_scales_from_ugm3() -> None:
    p = StagnationBoxParams(tau_h=4.0, e_local_g_s=1.0, area_m2=4.0e6)
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.5, night=True) for h in range(6)]
    ugm3 = box_series(met, p, units="ugm3")
    ppb = box_series(met, p, units="ppb")
    # H2S: ppb ≈ ugm3 * 24.45/34.08 at 25°C — strictly positive, < ugm3.
    assert np.all(ppb > 0.0)
    assert np.all(ppb < ugm3)


def test_box_handles_multi_hour_gaps() -> None:
    """A 2-hour timestamp gap takes a correspondingly larger step."""
    p = StagnationBoxParams(tau_h=3.0, e_local_g_s=2.0, area_m2=4.0e6)
    hourly = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.5, night=True) for h in (0, 1, 2)]
    gapped = [
        _met("2026-05-10T00:00:00-07:00", 1.5, night=True),
        _met("2026-05-10T02:00:00-07:00", 1.5, night=True),
    ]
    c_h = box_series(hourly, p, units="ugm3")
    c_g = box_series(gapped, p, units="ugm3")
    # Two 1-h steps from 0 vs one 2-h step from 0 should both rise; the
    # 2-h step should land near the hourly value at the same wall-time.
    assert c_g[-1] > c_g[0]
    assert abs(c_g[-1] - c_h[2]) / c_h[2] < 0.15


# ---------- backend ---------- #


def test_stagnation_box_backend_shape_and_info() -> None:
    b = StagnationBoxBackend()
    assert b.info.name == "stagnation_box"
    src = [SourceSpec(name="x", lat=32.54, lon=-117.05, emission_rate_g_s=1.0)]
    sources = [
        Source(name=s.name, lat=s.lat, lon=s.lon, emission_rate_g_s=s.emission_rate_g_s)
        for s in src
    ]
    receptors = [
        Receptor(name="A", lat=32.55, lon=-117.04),
        Receptor(name="B", lat=32.57, lon=-117.09),
    ]
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.2, night=True) for h in range(5)]
    arr = b.run_forward(sources, receptors, met, units="ppb")
    assert arr.shape == (5, 2)
    # Receptor-independent in v1: every receptor column identical.
    assert np.allclose(arr[:, 0], arr[:, 1])
    assert np.all(arr >= 0.0)


# ---------- dispatch wired into run_forward ---------- #


def _req(met_specs: list[MetSpec], **kw: object) -> ForwardRunRequest:
    return ForwardRunRequest(
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
        **kw,
    )


def _ms(ts: str, wind: float, night: bool) -> MetSpec:
    return MetSpec(
        timestamp=ts,
        wind_speed_ms=wind,
        wind_direction_deg=300.0,
        temperature_c=15.0,
        cloud_cover_frac=0.2,
        is_night=night,
    )


def test_schema_version_bumped() -> None:
    assert SCHEMA_VERSION == "0.3.0"


def test_dispatch_uses_box_on_stagnation_gaussian_otherwise() -> None:
    res = run_forward(
        _req(
            [
                _ms("2026-05-10T23:00:00-07:00", 1.4, night=True),  # stagnation → box
                _ms("2026-05-11T14:00:00-07:00", 5.0, night=False),  # advective → gaussian
            ]
        )
    )
    conc = np.array(res.concentrations)  # (n_t, n_r)
    assert res.stagnation_flags == [True, False]
    assert res.out_of_envelope is True
    # Box hour should be materially elevated vs the near-zero Gaussian
    # the plume would give at this receptor under calm wind.
    assert conc[0, 0] > 1.0
    assert res.summary["regime"] == "stagnation"
    assert res.summary.get("dispatch") == "regime"


def test_disable_regime_dispatch_is_pure_gaussian_backcompat() -> None:
    specs = [_ms("2026-05-10T23:00:00-07:00", 1.4, night=True)]
    dispatched = np.array(run_forward(_req(specs)).concentrations)
    pure = np.array(run_forward(_req(specs, disable_regime_dispatch=True)).concentrations)
    assert dispatched[0, 0] > pure[0, 0]  # box raises it; pure stays ~Gaussian
    r = run_forward(_req(specs, disable_regime_dispatch=True))
    assert r.out_of_envelope is True  # still flagged even when not dispatched
    assert r.summary.get("dispatch") == "disabled"


def test_force_stagnation_box_backend_for_all_hours() -> None:
    res = run_forward(
        _req(
            [
                _ms("2026-05-11T14:00:00-07:00", 5.0, night=False),  # advective hour
                _ms("2026-05-10T23:00:00-07:00", 1.4, night=True),
            ],
            backend="stagnation_box",
        )
    )
    conc = np.array(res.concentrations)
    # Forced box: even the advective hour is the box value, not Gaussian 0.
    assert np.all(conc[:, 0] >= 0.0)
    assert res.backend == "stagnation_box"
