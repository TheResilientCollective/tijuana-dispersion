"""Tests for the temperature-led emission driver feeding the
stagnation box (service issue #6).

Two paired experiments-repo studies established the design:
`box_calibration` (constant box rank-skill ceiling Spearman
0.127/0.218 on held-out Berry stagnation hours — necessary but not
sufficient) and `emission_driver_attribution` (`temperature_2m` alone
→ 0.33; the shipped `f_volatilization ∝ wind²` chain is *anti*-skilled
in this regime). So `E_local` becomes time-varying and **temperature-
led**, with the wind-quadratic volatilization and cosine-diel factors
deliberately excluded.

Tests-first per AGENTS.md. Parameter calibration (Q10, T_ref, E0)
is a paired experiments-repo follow-up — no calibration data lives in
this repo; v1 ships uncalibrated literature defaults.
"""

from __future__ import annotations

import numpy as np

from tijuana_dispersion import (
    ForwardRunRequest,
    MetCondition,
    MetSpec,
    ReceptorSpec,
    SourceSpec,
    run_forward,
)
from tijuana_dispersion.schemas import SCHEMA_VERSION, EmissionDriverParams
from tijuana_dispersion.stagnation import (
    H_MIX_BY_STABILITY_M,
    StagnationBoxParams,
    TemperatureEmissionParams,
    box_series,
    temperature_led_e_local,
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


# ---------- temperature-led production form ---------- #


def test_temperature_params_uncalibrated_literature_defaults() -> None:
    p = TemperatureEmissionParams()
    assert p.q10 == 2.5
    assert p.t_ref_c == 20.0


def test_temperature_form_q10_exact_and_monotone() -> None:
    """E(T_ref)=E0; E(T_ref+10)=E0*Q10; strictly increasing in T."""
    p = TemperatureEmissionParams(e0_g_s=2.0, q10=2.5, t_ref_c=20.0)
    met = [
        _met("2026-05-10T00:00:00-07:00", 1.0, True, temp=10.0),
        _met("2026-05-10T01:00:00-07:00", 1.0, True, temp=20.0),
        _met("2026-05-10T02:00:00-07:00", 1.0, True, temp=30.0),
    ]
    e = temperature_led_e_local(met, p)
    assert e.shape == (3,)
    assert np.isclose(e[1], 2.0)  # T == T_ref → E0
    assert np.isclose(e[2], 2.0 * 2.5)  # +10 °C → ×Q10
    assert np.isclose(e[0], 2.0 / 2.5)  # −10 °C → /Q10
    assert np.all(np.diff(e) > 0.0)


def test_temperature_form_independent_of_wind_and_diel() -> None:
    """The whole point of #6: no wind-quadratic volatilization, no
    cosine diel — only temperature moves E_local."""
    p = TemperatureEmissionParams(e0_g_s=1.0)
    a = [_met("2026-05-10T03:00:00-07:00", 0.5, True, temp=18.0)]
    b = [_met("2026-05-10T14:00:00-07:00", 9.0, False, temp=18.0)]
    assert np.isclose(temperature_led_e_local(a, p)[0], temperature_led_e_local(b, p)[0])


def test_optional_substrate_multiplies_elementwise() -> None:
    p = TemperatureEmissionParams(e0_g_s=1.0, q10=2.0, t_ref_c=20.0)
    met = [
        _met("2026-05-10T00:00:00-07:00", 1.0, True, temp=20.0),
        _met("2026-05-10T01:00:00-07:00", 1.0, True, temp=20.0),
    ]
    base = temperature_led_e_local(met, p)
    scaled = temperature_led_e_local(met, p, substrate=[1.0, 3.0])
    assert np.isclose(scaled[0], base[0])
    assert np.isclose(scaled[1], 3.0 * base[1])


# ---------- per-timestep E_local in the box ---------- #


def test_box_series_accepts_per_timestep_e_local_series() -> None:
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.4, True) for h in range(6)]
    series = np.full(6, 2.0)
    c_series = box_series(
        met, StagnationBoxParams(tau_h=4.0, e_local_g_s=series, area_m2=4.0e6), units="ugm3"
    )
    c_scalar = box_series(
        met, StagnationBoxParams(tau_h=4.0, e_local_g_s=2.0, area_m2=4.0e6), units="ugm3"
    )
    # A constant series must reduce EXACTLY to the scalar path.
    assert np.allclose(c_series, c_scalar)


def test_box_series_elementwise_emission_modulation() -> None:
    """A step-up in E_local mid-series accelerates accumulation."""
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.4, True) for h in range(8)]
    flat = box_series(
        met, StagnationBoxParams(tau_h=3.0, e_local_g_s=1.0, area_m2=4.0e6), units="ugm3"
    )
    stepped_e = np.array([1.0, 1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0])
    stepped = box_series(
        met, StagnationBoxParams(tau_h=3.0, e_local_g_s=stepped_e, area_m2=4.0e6), units="ugm3"
    )
    assert np.allclose(stepped[:4], flat[:4])
    assert np.all(stepped[4:] > flat[4:])


def test_box_series_wrong_length_series_raises() -> None:
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.4, True) for h in range(5)]
    try:
        box_series(met, StagnationBoxParams(e_local_g_s=[1.0, 2.0]), units="ugm3")
    except ValueError:
        return
    raise AssertionError("expected ValueError on length-mismatched e_local series")


def test_box_series_scalar_path_unchanged_regression() -> None:
    """Issue-#3 scalar steady state must be byte-for-byte unchanged."""
    p = StagnationBoxParams(tau_h=4.0, e_local_g_s=2.0, area_m2=4.0e6)
    met = [_met(f"2026-05-10T{h:02d}:00:00-07:00", 1.5, True) for h in range(20)]
    c = box_series(met, p, units="ugm3")
    c_star = (2.0 * 1e6) * (4.0 * 3600.0) / (4.0e6 * H_MIX_BY_STABILITY_M["F"])
    assert abs(c[-1] - c_star) / c_star < 0.05


# ---------- schema (additive, minor bump) ---------- #


def test_schema_version_bumped_to_0_4_0() -> None:
    assert SCHEMA_VERSION == "0.4.0"


def test_emission_driver_request_fields_default_off() -> None:
    """Pre-0.4.0 payloads still parse: driver off, params None."""
    req = ForwardRunRequest(
        sources=[SourceSpec(name="x", lat=32.5, lon=-117.0, emission_rate_g_s=1.0)],
        receptors=[ReceptorSpec(name="r", lat=32.55, lon=-117.04)],
        meteorology=[
            MetSpec(
                timestamp="2026-05-10T23:00:00-07:00",
                wind_speed_ms=1.4,
                wind_direction_deg=300.0,
                temperature_c=15.0,
                cloud_cover_frac=0.2,
                is_night=True,
            )
        ],
    )
    assert req.emission_driver is False
    assert req.emission_driver_params is None
    p = EmissionDriverParams()
    assert p.q10 == 2.5
    assert p.t_ref_c == 20.0
    assert p.e0_g_s is None  # None → use Σ source rates


# ---------- dispatch wiring ---------- #


def _ms(ts: str, wind: float, night: bool, temp: float) -> MetSpec:
    return MetSpec(
        timestamp=ts,
        wind_speed_ms=wind,
        wind_direction_deg=300.0,
        temperature_c=temp,
        cloud_cover_frac=0.2,
        is_night=night,
    )


def _req(temp: float, **kw: object) -> ForwardRunRequest:
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
        meteorology=[_ms("2026-05-10T23:00:00-07:00", 1.4, True, temp)],
        units="ugm3",
        cache_key=None,
        **kw,
    )


def test_emission_driver_off_is_temperature_insensitive_in_ugm3() -> None:
    """#3 constant box: same E_local regardless of temperature (µg/m³
    removes the ppb-conversion temperature confound)."""
    cold = np.array(run_forward(_req(10.0)).concentrations)[0, 0]
    warm = np.array(run_forward(_req(30.0)).concentrations)[0, 0]
    assert np.isclose(cold, warm)


def test_emission_driver_on_scales_box_by_q10() -> None:
    """With the driver on, a +20 °C hour is Q10^2 hotter in emission,
    so the box concentration scales by ~Q10^2 (E0 = Σ source rates)."""
    cold = np.array(run_forward(_req(10.0, emission_driver=True)).concentrations)[0, 0]
    warm = np.array(run_forward(_req(30.0, emission_driver=True)).concentrations)[0, 0]
    assert warm > cold
    assert np.isclose(warm / cold, 2.5**2, rtol=0.02)  # Q10=2.5, ΔT=20 °C


def test_emission_driver_summary_flag_and_backcompat() -> None:
    on = run_forward(_req(25.0, emission_driver=True))
    off = run_forward(_req(25.0))
    assert on.summary.get("dispatch") == "regime"
    assert on.summary.get("emission_driver") is True
    assert off.summary.get("emission_driver") is False
    assert on.stagnation_flags == [True]
    assert on.out_of_envelope is True
