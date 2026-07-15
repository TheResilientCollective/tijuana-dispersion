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

import math

import numpy as np
import pytest

from tijuana_dispersion import (
    ForwardRunRequest,
    MetCondition,
    MetSpec,
    Receptor,
    ReceptorSpec,
    Source,
    SourceSpec,
    StagnationBoxBackend,
    StagnationBoxSpec,
    run_forward,
    service,
)
from tijuana_dispersion.schemas import SCHEMA_VERSION
from tijuana_dispersion.stagnation import (
    H_MIX_BY_STABILITY_M,
    StagnationBoxParams,
    box_series,
    distance_weighted_e_local,
    drainage_weighted_e_local,
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
    # 0.4.0 (issue #6) → 0.5.0 (receptor-dependent stagnation box).
    assert SCHEMA_VERSION == "0.5.0"


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


# ---------- receptor-dependent kernel (schema 0.5.0) ---------- #


def _kernel_sources() -> list[Source]:
    """One strong source near NESTOR (Saturn Blvd Bridge geometry), one
    equal-rate source ~4 km south (Stewart's Drain geometry)."""
    return [
        Source(name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, emission_rate_g_s=1.0),
        Source(name="Stewart's Drain", lat=32.54064, lon=-117.05801, emission_rate_g_s=1.0),
    ]


def _kernel_receptors() -> list[Receptor]:
    return [
        Receptor(name="NESTOR - BES", lat=32.567097, lon=-117.090656),  # 0.9 km from Saturn
        Receptor(name="IB CIVIC CTR", lat=32.5859, lon=-117.1132),  # ~3.5 km away
    ]


def test_distance_weighted_e_local_limits() -> None:
    sources = _kernel_sources()
    nestor = _kernel_receptors()[0]
    total = sum(s.emission_rate_g_s for s in sources)
    # Huge lambda recovers the lumped sum.
    assert distance_weighted_e_local(sources, nestor, 1.0e12) == pytest.approx(total, rel=1e-6)
    # Small lambda: only the nearby source contributes materially, and the
    # result is bounded by its rate.
    e_small = distance_weighted_e_local(sources, nestor, 500.0)
    assert 0.0 < e_small < sources[0].emission_rate_g_s
    # Larger lambda ⇒ more emission reaches the receptor (monotone).
    assert distance_weighted_e_local(sources, nestor, 2000.0) > e_small
    with pytest.raises(ValueError, match="lambda_m"):
        distance_weighted_e_local(sources, nestor, 0.0)
    assert distance_weighted_e_local([], nestor, 1000.0) == 0.0


def test_backend_lambda_none_is_v1_exactly() -> None:
    sources = _kernel_sources()
    receptors = _kernel_receptors()
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.2, night=True) for h in range(4)]
    v1 = StagnationBoxBackend().run_forward(sources, receptors, met, units="ppb")
    v1_explicit = StagnationBoxBackend(lambda_m=None).run_forward(
        sources, receptors, met, units="ppb"
    )
    assert np.array_equal(v1, v1_explicit)
    assert np.allclose(v1[:, 0], v1[:, 1])  # receptor-independent


def test_backend_kernel_orders_receptors_by_proximity() -> None:
    sources = _kernel_sources()
    receptors = _kernel_receptors()
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.2, night=True) for h in range(4)]
    arr = StagnationBoxBackend(lambda_m=1000.0).run_forward(sources, receptors, met, units="ppb")
    assert arr.shape == (4, 2)
    # NESTOR (0.9 km from Saturn Blvd Bridge) accumulates more than IB (~3.5 km).
    assert np.all(arr[:, 0] > arr[:, 1])
    # Huge lambda converges to the v1 lumped columns.
    v1 = StagnationBoxBackend().run_forward(sources, receptors, met, units="ppb")
    big = StagnationBoxBackend(lambda_m=1.0e12).run_forward(sources, receptors, met, units="ppb")
    assert np.allclose(big, v1, rtol=1e-6)


def test_request_stagnation_box_spec_dispatch() -> None:
    """run_forward honors stagnation_box: receptor-dependent columns on
    stagnation hours; omitting the spec keeps v1 behaviour."""
    met_specs = [_ms("2026-03-14T02:00:00-08:00", 1.0, night=True)]
    base = ForwardRunRequest(
        sources=[
            SourceSpec(
                name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, emission_rate_g_s=1.0
            ),
            SourceSpec(name="Stewart's Drain", lat=32.54064, lon=-117.05801, emission_rate_g_s=1.0),
        ],
        receptors=[
            ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656),
            ReceptorSpec(name="IB CIVIC CTR", lat=32.5859, lon=-117.1132),
        ],
        meteorology=met_specs,
    )
    plain = run_forward(base)
    a = np.asarray(plain.concentrations)
    assert a[0, 0] == pytest.approx(a[0, 1])  # v1: identical columns

    kernel = run_forward(
        base.model_copy(update={"stagnation_box": StagnationBoxSpec(lambda_m=1000.0)})
    )
    b = np.asarray(kernel.concentrations)
    assert b[0, 0] > b[0, 1]  # NESTOR column now larger

    # tau override moves the concentration (longer residence ⇒ higher C).
    slow = run_forward(
        base.model_copy(update={"stagnation_box": StagnationBoxSpec(lambda_m=1000.0, tau_h=6.0)})
    )
    c = np.asarray(slow.concentrations)
    assert c[0, 0] > b[0, 0]


def test_kernel_composes_with_emission_driver() -> None:
    met_specs = [_ms("2026-03-14T02:00:00-08:00", 1.0, night=True)]
    req = ForwardRunRequest(
        sources=[
            SourceSpec(
                name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, emission_rate_g_s=1.0
            ),
            SourceSpec(name="Stewart's Drain", lat=32.54064, lon=-117.05801, emission_rate_g_s=1.0),
        ],
        receptors=[
            ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656),
            ReceptorSpec(name="IB CIVIC CTR", lat=32.5859, lon=-117.1132),
        ],
        meteorology=met_specs,
        emission_driver=True,
        stagnation_box=StagnationBoxSpec(lambda_m=1000.0),
    )
    arr = np.asarray(run_forward(req).concentrations)
    assert arr[0, 0] > arr[0, 1]  # geometry survives the driver


# ---------- drainage kernel (Saturn Blvd mechanism) ---------- #

VALLEY_BEARING = 280.0  # Tijuana River drainage direction (flow toward WNW)


def _valley_sources() -> list[Source]:
    """The real channel chain, up-valley (E) to down-valley (W)."""
    return [
        Source(name="Dairy Mart Bridge", lat=32.5485, lon=-117.0643, emission_rate_g_s=1.0),
        Source(name="Hollister St Bridge N", lat=32.5542, lon=-117.0841, emission_rate_g_s=1.0),
        Source(name="Saturn Blvd Bridge", lat=32.5594, lon=-117.0930, emission_rate_g_s=1.0),
    ]


def test_drainage_kernel_splits_nestor_from_san_ysidro() -> None:
    """The decisive geometry: NESTOR sits down-valley of the channel
    chain, SAN YSIDRO up-valley — the isotropic kernel provably cannot
    split them (2026-07-11 lambda sweep); the directional one must."""
    sources = _valley_sources()
    nestor = Receptor(name="NESTOR - BES", lat=32.5671, lon=-117.0907)
    sy = Receptor(name="SAN YSIDRO", lat=32.5528, lon=-117.0473)
    e_nestor = drainage_weighted_e_local(sources, nestor, 3000.0, 500.0, VALLEY_BEARING)
    e_sy = drainage_weighted_e_local(sources, sy, 3000.0, 500.0, VALLEY_BEARING)
    assert e_nestor > 3.0 * e_sy


def test_drainage_kernel_directionality() -> None:
    src = [Source(name="s", lat=32.5594, lon=-117.0930, emission_rate_g_s=1.0)]
    # Receptor 1 km downstream (bearing 280 from the source) vs 1 km upstream.
    phi = math.radians(VALLEY_BEARING)
    dlat = math.cos(phi) * 1000.0 / 111_320.0
    dlon = math.sin(phi) * 1000.0 / (111_320.0 * math.cos(math.radians(32.56)))
    down = Receptor(name="down", lat=32.5594 + dlat, lon=-117.0930 + dlon)
    up = Receptor(name="up", lat=32.5594 - dlat, lon=-117.0930 - dlon)
    e_down = drainage_weighted_e_local(src, down, 3000.0, 300.0, VALLEY_BEARING)
    e_up = drainage_weighted_e_local(src, up, 3000.0, 300.0, VALLEY_BEARING)
    # Downstream decays on the 3000 m scale, upstream on the 300 m scale.
    assert e_down > 5.0 * e_up
    with pytest.raises(ValueError, match="positive"):
        drainage_weighted_e_local(src, down, -1.0, 300.0, VALLEY_BEARING)
    assert drainage_weighted_e_local([], down, 3000.0, 300.0, VALLEY_BEARING) == 0.0


def test_backend_drainage_requires_lambda() -> None:
    with pytest.raises(ValueError, match="requires lambda_m"):
        StagnationBoxBackend(drainage_bearing_deg=280.0)


def test_request_drainage_spec_dispatch() -> None:
    met_specs = [_ms("2026-03-14T02:00:00-08:00", 1.0, night=True)]
    req = ForwardRunRequest(
        sources=[
            SourceSpec(name=s.name, lat=s.lat, lon=s.lon, emission_rate_g_s=1.0)
            for s in _valley_sources()
        ],
        receptors=[
            ReceptorSpec(name="NESTOR - BES", lat=32.5671, lon=-117.0907),
            ReceptorSpec(name="SAN YSIDRO", lat=32.5528, lon=-117.0473),
        ],
        meteorology=met_specs,
        stagnation_box=StagnationBoxSpec(
            lambda_m=3000.0, drainage_bearing_deg=280.0, lambda_cross_m=500.0
        ),
    )
    arr = np.asarray(run_forward(req).concentrations)
    assert arr[0, 0] > 3.0 * arr[0, 1]  # NESTOR >> SY on the stagnation hour


def test_cache_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """DISPERSION_DISABLE_CACHE=1 computes without reading or writing cache."""
    met_specs = [_ms("2026-03-14T02:00:00-08:00", 1.0, night=True)]
    req = _req(met_specs)
    monkeypatch.setenv("DISPERSION_DISABLE_CACHE", "1")
    before = sorted(service.CACHE_DIR.glob("forward_*.json"))
    r1 = run_forward(req)
    assert sorted(service.CACHE_DIR.glob("forward_*.json")) == before  # nothing written
    monkeypatch.delenv("DISPERSION_DISABLE_CACHE")
    r2 = run_forward(req)  # cached path, same physics
    assert np.allclose(np.asarray(r1.concentrations), np.asarray(r2.concentrations))
