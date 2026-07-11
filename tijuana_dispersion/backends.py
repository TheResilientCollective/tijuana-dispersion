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

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .core import (
    MetCondition,
    Receptor,
    Source,
    forward_run,
    forward_run_per_source,
)
from .stagnation import (
    StagnationBoxParams,
    box_series,
    distance_weighted_e_local,
    drainage_weighted_e_local,
)


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
    """
    TODO: implement. Pure-Python CALPUFF-style puff model.

    Plan: at each timestep, release one Gaussian puff per source.
    Active puffs are advected by the current wind, age (σ grows as √t),
    and contribute to receptor concentration weighted by distance.
    Puffs deactivate when they leave the domain or fall below a
    concentration threshold.

    Estimated implementation: ~300 lines, one weekend.
    """

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(name="puff", version="0.0.0", notes="not yet implemented")

    def run_forward(
        self,
        sources: list[Source],
        receptors: list[Receptor],
        met: list[MetCondition],
        units: Literal["ppb", "ugm3"] = "ppb",
    ) -> np.ndarray:
        raise NotImplementedError(
            "Lagrangian puff backend not yet implemented. "
            "See the planning doc for the design sketch."
        )


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

    def __init__(
        self,
        params: StagnationBoxParams | None = None,
        lambda_m: float | None = None,
        drainage_bearing_deg: float | None = None,
        lambda_cross_m: float = 500.0,
    ):
        self._params = params
        self._lambda_m = lambda_m
        self._drainage_bearing_deg = drainage_bearing_deg
        self._lambda_cross_m = lambda_cross_m
        if drainage_bearing_deg is not None and lambda_m is None:
            raise ValueError("drainage_bearing_deg requires lambda_m (the along-valley decay)")

    @property
    def info(self) -> BackendInfo:
        kernel = (
            f"receptor-dependent (lambda={self._lambda_m:.0f} m)"
            if self._lambda_m is not None
            else "receptor-independent v1"
        )
        return BackendInfo(
            name="stagnation_box",
            version="0.2.0",
            notes=f"calm-night accumulation box; {kernel}; uncalibrated defaults",
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
        if self._lambda_m is None:
            series = box_series(met, params, units=units)  # (n_t,)
            # Receptor-independent: broadcast the box value across columns.
            return np.repeat(series[:, None], len(receptors), axis=1)

        # Receptor-dependent kernel: each receptor's box is fed by the
        # distance-weighted local emission (stagnation.distance_weighted_
        # e_local); tau/area come from the shared params. Any explicit
        # e_local_g_s in params is interpreted as a *lumped* series and
        # rescaled per receptor by the kernel weight w_r = E_r / Σ rates,
        # so a time-varying driver composes with the geometry.
        total = float(sum(s.emission_rate_g_s for s in sources))
        cols = []
        for rec in receptors:
            if self._drainage_bearing_deg is not None:
                e_r = drainage_weighted_e_local(
                    sources,
                    rec,
                    lambda_along_m=self._lambda_m,
                    lambda_cross_m=self._lambda_cross_m,
                    bearing_deg=self._drainage_bearing_deg,
                )
            else:
                e_r = distance_weighted_e_local(sources, rec, self._lambda_m)
            w_r = e_r / total if total > 0.0 else 0.0
            e_local = params.e_local_g_s
            if isinstance(e_local, (int, float)):
                rec_params = StagnationBoxParams(
                    tau_h=params.tau_h,
                    e_local_g_s=float(e_local) * w_r if self._params is not None else e_r,
                    area_m2=params.area_m2,
                )
            else:
                rec_params = StagnationBoxParams(
                    tau_h=params.tau_h,
                    e_local_g_s=np.asarray(e_local, dtype=float) * w_r,
                    area_m2=params.area_m2,
                )
            cols.append(box_series(met, rec_params, units=units))
        return np.stack(cols, axis=1)


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
