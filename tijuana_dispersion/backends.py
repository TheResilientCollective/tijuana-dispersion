"""
Backend abstraction and ensemble dispatcher for the dispersion service.

A Backend is anything that takes (sources, receptors, meteorology) and
returns a concentration array. The current implementations:

  - LocalGaussianPlumeBackend: in-process, uses core.py
  - RemoteHTTPBackend: HTTP POST to another Railway service
  - LagrangianPuffBackend: in-process, pure Python (TODO: implement)

The EnsembleBackend takes a list of (Backend, weight) and runs all of them,
combining results into a single ForwardRunResult.

Design notes:

- Every backend returns the same array shape so the combiner is just
  a weighted sum.
- Backends run sequentially in the simple version. For Railway,
  parallelism with httpx.AsyncClient is a 20-line upgrade once we
  have more than one remote backend.
- Per-backend metadata is preserved in result.summary so we can audit
  which backends contributed what to the final concentration.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import numpy as np

from .core import (
    BRIGGS_RURAL,
    MetCondition,
    Receptor,
    Source,
    forward_run,
    forward_run_per_source,
    latlon_to_local_xy,
    pasquill_stability,
    ugm3_to_ppb_h2s,
)
from .stagnation import StagnationBoxParams, box_series


@dataclass
class BackendInfo:
    """Identification and provenance for a backend."""

    name: str  # 'gaussian_plume', 'puff', 'hysplit_remote', etc.
    version: str
    runtime_ms: int = 0
    cached: bool = False
    notes: str = ""


# ---------- Abstract base ---------- #


class Backend(ABC):
    """A dispersion model backend. All backends share the same I/O shape."""

    @property
    @abstractmethod
    def info(self) -> BackendInfo: ...

    @abstractmethod
    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        """
        Returns concentration array of shape (n_times, n_receptors).
        Units = 'ppb' or 'ugm3'.
        """
        ...

    def run_forward_per_source(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        """
        Returns per-source concentration array of shape
        (n_times, n_receptors, n_sources). Default implementation
        loops one source at a time. Subclasses can override with
        a vectorized version.
        """
        n_t, n_r, n_s = len(met), len(receptors), len(sources)
        out = np.zeros((n_t, n_r, n_s))
        for s_idx, src in enumerate(sources):
            out[:, :, s_idx] = self.run_forward([src], receptors, met, units)
        return out


# ---------- Concrete backends ---------- #


class LocalGaussianPlumeBackend(Backend):
    """In-process Gaussian plume from core.py. Always available."""

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(name="gaussian_plume", version="0.1.0")

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        return forward_run(sources, receptors, met, units=units)

    def run_forward_per_source(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        return forward_run_per_source(sources, receptors, met, units=units)


class LagrangianPuffBackend(Backend):
    """Pure-Python (numpy) Gaussian puff model (issue #1).

    At each timestep every source releases puffs (mass =
    rate·Δt); existing puffs are advected by the current wind, their
    σ_y/σ_z grow with travelled path via the Briggs coefficients, and
    receptor concentration is the sum over active puffs of the
    standard 3-D Gaussian-puff kernel with ground reflection. Puffs
    that leave the receptor domain are pruned.

    Each hourly step is sub-divided into K sub-puffs per source so the
    discrete along-wind sum approximates the continuous release: with
    σ_x ≡ σ_y the sum reduces analytically to the steady-state
    Gaussian plume Q/(2π u σ_y σ_z)·… in steady wind (the issue's
    10 %-agreement criterion), while a cold start / step change shows
    the physically-correct delayed-then-rising transient the plume
    cannot represent.

    Out of scope per the design doc: deposition, buoyant rise,
    chemistry (all negligible at the 1-hour transport timescale).
    """

    def __init__(
        self,
        target_spacing_m: float = 15.0,
        max_substeps: int = 1200,
        prune_distance_m: float = 12_000.0,
        min_wind_ms: float = 0.5,
    ) -> None:
        self.target_spacing_m = target_spacing_m
        self.max_substeps = max_substeps
        self.prune_distance_m = prune_distance_m
        self.min_wind_ms = min_wind_ms

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(
            name="puff",
            version="0.1.0",
            notes="pure-Python Gaussian puff; steady-state → plume, transient-aware",
        )

    @staticmethod
    def _dt_seconds(met: list[MetCondition]) -> np.ndarray:
        """Per-timestep Δt (s) from ISO timestamps; 3600 s fallback."""
        n = len(met)
        out = np.full(n, 3600.0)
        ts: list[datetime | None] = []
        for m in met:
            try:
                ts.append(datetime.fromisoformat(m.timestamp))
            except ValueError:
                ts.append(None)
        for i in range(n):
            a = ts[i - 1] if i > 0 else None
            b = ts[i]
            if a is not None and b is not None:
                d = (b - a).total_seconds()
                if d > 0:
                    out[i] = d
            elif i + 1 < n and ts[i] is not None and ts[i + 1] is not None:
                d = (ts[i + 1] - ts[i]).total_seconds()  # type: ignore[operator]
                if d > 0:
                    out[i] = d
        return out

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        n_t, n_r = len(met), len(receptors)
        out = np.zeros((n_t, n_r))
        if n_t == 0 or n_r == 0 or not sources:
            return out

        # Common local frame centred on the first source (metres, ENU).
        lat0, lon0 = sources[0].lat, sources[0].lon
        rx, ry = latlon_to_local_xy(
            np.array([r.lat for r in receptors], dtype=float),
            np.array([r.lon for r in receptors], dtype=float),
            lat0,
            lon0,
        )
        rz = np.array([r.height_m for r in receptors], dtype=float)
        sx, sy = latlon_to_local_xy(
            np.array([s.lat for s in sources], dtype=float),
            np.array([s.lon for s in sources], dtype=float),
            lat0,
            lon0,
        )
        s_rate = np.array([s.emission_rate_g_s for s in sources], dtype=float)
        s_h = np.array([s.height_m for s in sources], dtype=float)
        emit = s_rate > 0.0  # zero-rate sources release nothing (exact 0)
        dt_s = self._dt_seconds(met)

        # Dynamic puff state (1-D arrays grown/compacted each step).
        px = np.empty(0)
        py = np.empty(0)
        pmass = np.empty(0)  # µg
        ppath = np.empty(0)  # travelled distance, m (drives σ growth)
        cy = np.empty((0, 3))  # Briggs σ_y coeffs (a, b, c) per puff
        cz = np.empty((0, 3))  # Briggs σ_z coeffs
        psh = np.empty(0)  # source height per puff

        for t in range(n_t):
            m = met[t]
            u = max(m.wind_speed_ms, self.min_wind_ms)
            # Meteorological "from" → unit "to" vector in (east, north).
            phi = math.radians((m.wind_direction_deg + 180.0) % 360.0)
            ew = math.sin(phi)
            nw = math.cos(phi)
            dt = float(dt_s[t])

            # Advect every existing puff by the full step.
            disp = u * dt
            if px.size:
                px = px + disp * ew
                py = py + disp * nw
                ppath = ppath + disp

            # Release K sub-puffs per emitting source this step. A
            # sub-puff released at sub-index k is advected by the
            # remaining (K-1-k) sub-steps within the step, so its
            # within-step path/offset is known in closed form — fully
            # vectorised, no inner loop.
            k_n = int(np.clip(math.ceil(u * dt / self.target_spacing_m), 1, self.max_substeps))
            if emit.any():
                dtau = dt / k_n
                stab = pasquill_stability(u, m.is_night, m.cloud_cover_frac)
                ay, by, cyc = BRIGGS_RURAL[stab]["sy"]
                az, bz, czc = BRIGGS_RURAL[stab]["sz"]
                offs = (k_n - 1 - np.arange(k_n)) * (u * dtau)  # (K,) path each
                n_e = int(emit.sum())
                off_rep = np.tile(offs, n_e)  # (K*n_e,)
                src_idx = np.repeat(np.where(emit)[0], k_n)
                new_x = sx[src_idx] + off_rep * ew
                new_y = sy[src_idx] + off_rep * nw
                new_mass = s_rate[src_idx] * dtau * 1.0e6  # g/s·s → µg
                new_path = off_rep.copy()
                n_new = new_x.size
                px = np.concatenate([px, new_x])
                py = np.concatenate([py, new_y])
                pmass = np.concatenate([pmass, new_mass])
                ppath = np.concatenate([ppath, new_path])
                psh = np.concatenate([psh, s_h[src_idx]])
                cy = np.concatenate([cy, np.tile([ay, by, cyc], (n_new, 1))])
                cz = np.concatenate([cz, np.tile([az, bz, czc], (n_new, 1))])

            if not px.size:
                continue

            # σ(path) from the per-puff Briggs coefficients (σ_x ≡ σ_y).
            xs = np.maximum(ppath, 1.0)
            sig_y = cy[:, 0] * xs * np.power(1.0 + cy[:, 1] * xs, cy[:, 2])
            sig_z = cz[:, 0] * xs * np.power(1.0 + cz[:, 1] * xs, cz[:, 2])
            sig_y = np.maximum(sig_y, 1e-6)
            sig_z = np.maximum(sig_z, 1e-6)
            norm = pmass / ((2.0 * math.pi) ** 1.5 * sig_y * sig_y * sig_z)

            for r in range(n_r):
                de = rx[r] - px
                dn = ry[r] - py
                along = de * ew + dn * nw
                cross = -de * nw + dn * ew
                vert = np.exp(-((rz[r] - psh) ** 2) / (2.0 * sig_z**2)) + np.exp(
                    -((rz[r] + psh) ** 2) / (2.0 * sig_z**2)
                )
                conc = (
                    norm
                    * np.exp(-(along**2) / (2.0 * sig_y**2))
                    * np.exp(-(cross**2) / (2.0 * sig_y**2))
                    * vert
                )
                out[t, r] = float(conc.sum())

            if units == "ppb":
                for r in range(n_r):
                    out[t, r] = ugm3_to_ppb_h2s(out[t, r], m.temperature_c)

            # Prune puffs that have left the receptor domain.
            d2 = np.full(px.size, np.inf)
            for r in range(n_r):
                d2 = np.minimum(d2, (rx[r] - px) ** 2 + (ry[r] - py) ** 2)
            keep = d2 <= self.prune_distance_m**2
            if not keep.all():
                px, py = px[keep], py[keep]
                pmass, ppath, psh = pmass[keep], ppath[keep], psh[keep]
                cy, cz = cy[keep], cz[keep]

        return out


class StagnationBoxBackend(Backend):
    """Calm-night accumulation box (service issue #3).

    Implements the box recurrence in ``stagnation.box_series``: the
    right zeroth-order physics when the nocturnal surface layer
    decouples and the Gaussian-plume backends have ~no skill ("you
    cannot trap a plume that never arrived").

    v1 is intentionally **receptor-independent** — the box represents a
    neighbourhood-scale accumulation volume, so every receptor column
    is identical. The local emission feeding the box is the sum of the
    supplied source rates; ``tau_h`` and ``area_m2`` use the
    (uncalibrated) defaults in :class:`StagnationBoxParams`. Calibrating
    those against the 242 Berry >100 ppb hours is an experiments-repo
    follow-up (no calibration data lives in this service repo).
    """

    def __init__(self, params: StagnationBoxParams | None = None):
        self._params = params

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(
            name="stagnation_box",
            version="0.1.0",
            notes="calm-night accumulation box; receptor-independent v1; uncalibrated defaults",
        )

    def _resolve_params(self, sources: list[Source]) -> StagnationBoxParams:
        if self._params is not None:
            return self._params
        e_local = float(sum(s.emission_rate_g_s for s in sources))
        return StagnationBoxParams(e_local_g_s=e_local)

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        params = self._resolve_params(sources)
        series = box_series(met, params, units=units)  # (n_t,)
        # Receptor-independent: broadcast the box value across columns.
        return np.repeat(series[:, None], len(receptors), axis=1)


class RemoteHTTPBackend(Backend):
    """
    Forwards a request to another HTTP-served dispersion service.
    Used to call your private HYSPLIT Docker (deployed as a Railway
    sibling service) or a STILT/FLEXPART service on a separate VM.

    The remote service must implement the same /forward endpoint contract.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        version: str = "unknown",
        bearer_token: str | None = None,
        timeout_s: float = 60.0,
    ):
        self._name = name
        self._version = version
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.timeout_s = timeout_s

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(name=self._name, version=self._version)

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        # httpx is optional; import lazily so the rest of the package still
        # imports when httpx isn't installed.
        try:
            import httpx  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError("RemoteHTTPBackend requires httpx. pip install httpx") from e

        # Build request body matching the service's ForwardRunRequest schema
        body = {
            "schema_version": "0.1.0",
            "backend": "auto",  # remote service decides
            "sources": [
                {
                    "name": s.name,
                    "lat": s.lat,
                    "lon": s.lon,
                    "emission_rate_g_s": s.emission_rate_g_s,
                    "height_m": s.height_m,
                    "archetype": s.archetype,
                }
                for s in sources
            ],
            "receptors": [
                {"name": r.name, "lat": r.lat, "lon": r.lon, "height_m": r.height_m}
                for r in receptors
            ],
            "meteorology": [
                {
                    "timestamp": m.timestamp,
                    "wind_speed_ms": m.wind_speed_ms,
                    "wind_direction_deg": m.wind_direction_deg,
                    "temperature_c": m.temperature_c,
                    "cloud_cover_frac": m.cloud_cover_frac,
                    "is_night": m.is_night,
                }
                for m in met
            ],
            "units": units,
        }
        headers = {}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(f"{self.base_url}/forward", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()

        return np.array(data["concentrations"])


# ---------- Ensemble ---------- #


@dataclass
class EnsembleMember:
    backend: Backend
    weight: float = 1.0


class EnsembleBackend(Backend):
    """
    Runs N backends, weight-combines their concentration outputs.

    Weights are normalized to sum to 1 (per-receptor weights would be
    a small extension; not implemented yet).

    Per-backend results and runtimes are exposed via member_results
    after each call, for diagnostics and audit.
    """

    def __init__(self, members: list[EnsembleMember]):
        if not members:
            raise ValueError("EnsembleBackend needs at least one member")
        total = sum(m.weight for m in members)
        if total <= 0:
            raise ValueError("EnsembleBackend weights must sum to > 0")
        self.members = [EnsembleMember(backend=m.backend, weight=m.weight / total) for m in members]
        self.member_results: list[dict[str, Any]] = []

    @property
    def info(self) -> BackendInfo:
        names = "+".join(m.backend.info.name for m in self.members)
        return BackendInfo(name=f"ensemble[{names}]", version="0.1.0")

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        self.member_results = []
        results: list[np.ndarray] = []
        weights: list[float] = []
        for m in self.members:
            t0 = time.time()
            try:
                arr = m.backend.run_forward(sources, receptors, met, units)
                rt = int((time.time() - t0) * 1000)
                self.member_results.append(
                    {
                        "name": m.backend.info.name,
                        "weight": m.weight,
                        "runtime_ms": rt,
                        "max_concentration": float(np.max(arr)),
                        "ok": True,
                    }
                )
                results.append(arr)
                weights.append(m.weight)
            except Exception as e:
                self.member_results.append(
                    {
                        "name": m.backend.info.name,
                        "weight": m.weight,
                        "runtime_ms": int((time.time() - t0) * 1000),
                        "ok": False,
                        "error": str(e),
                    }
                )
                # Skip failed backend; renormalize remaining
        if not results:
            raise RuntimeError("All ensemble backends failed")
        # Renormalize in case some failed
        weights_arr = np.array(weights) / sum(weights)
        stacked = np.stack(results, axis=0)  # (n_backends, n_t, n_r)
        combined: np.ndarray = (stacked * weights_arr[:, None, None]).sum(axis=0)
        return combined


# ---------- Convenience: build a simple ensemble ---------- #


def build_default_ensemble(
    hysplit_url: str | None = None,
    hysplit_token: str | None = None,
    plume_weight: float = 0.4,
    puff_weight: float = 0.3,
    hysplit_weight: float = 0.3,
) -> EnsembleBackend:
    """
    Construct the default ensemble for this project:
    Gaussian plume (always) + puff (when implemented) + remote HYSPLIT.

    If hysplit_url is None, the remote HYSPLIT backend is omitted and
    weights are renormalized to plume + puff only. This makes the
    ensemble usable end-to-end on Railway from day one.
    """
    members = [
        EnsembleMember(LocalGaussianPlumeBackend(), weight=plume_weight),
    ]
    # Puff is currently a stub; including it would just fail during the
    # ensemble run and be skipped, so we hold off until implemented.
    # When ready: members.append(EnsembleMember(LagrangianPuffBackend(), weight=puff_weight))

    if hysplit_url:
        members.append(
            EnsembleMember(
                RemoteHTTPBackend(
                    name="hysplit_remote",
                    base_url=hysplit_url,
                    bearer_token=hysplit_token,
                ),
                weight=hysplit_weight,
            )
        )

    return EnsembleBackend(members)
