# Architecture — `tijuana-dispersion`

## What this service is

A FastAPI application providing forward dispersion modeling and emission inversion for the H₂S monitoring network in the Tijuana River Valley. The service is deployed to Railway as an always-on, low-latency endpoint. Larger batch workloads (Sobol sensitivity, MCMC, leave-one-event-out CV) run separately on the National Research Platform via Dagster, but call back into the same package for forward-model evaluation when convenient.

The service is **not** a calibration tool. Calibration scripts and experiments live in the companion repo `tijuana-dispersion-experiments`. This service provides the substrate they consume.

## Package layout

```
tijuana_dispersion/
├── core.py          # dispersion physics: Gaussian plume, Briggs σ, Pasquill stability
├── schemas.py       # Pydantic API contract; versioned
├── service.py       # request dispatch, content-addressed disk cache, NNLS inversion
├── calibration.py   # distributed-source generators, bounded NNLS, wind-conditional diagnostics
├── backends.py      # backend protocol, RemoteHTTPBackend, EnsembleBackend
├── emissions.py     # emissions-model skeleton with bridge points for external implementations
└── api.py           # FastAPI app
```

Each module has a single responsibility. `core.py` is the only place dispersion physics lives. `schemas.py` is the only place the API contract lives. New code goes into the module whose responsibility it most closely matches; if no module fits, that's a signal to think about whether a new module is justified rather than appending to whichever one is closest.

## Backend tiers

The service is designed to dispatch forward-modeling requests to one of several backends. Different backends have different cost-fidelity tradeoffs.

**Tier 1 — built into the package, runs in-process on Railway**

- `LocalGaussianPlumeBackend` (working) — steady-state Gaussian plume with Briggs rural σ coefficients. Sub-100 ms for typical workloads. Limitation: assumes steady state, breaks down for transient releases (spill events) and has ~no skill in calm-nocturnal stagnation ("you cannot trap a plume that never arrived").
- `StagnationBoxBackend` (working) — calm-night accumulation box (issue #3). Exact box recurrence `C[t] = C[t-1]·e^(−Δt/τ) + C*·(1−e^(−Δt/τ))` with `C* = E·τ/(A·H_mix)` and `H_mix` keyed off Pasquill stability. Receptor-independent v1. The default `gaussian_plume` request now performs per-timestep **regime dispatch**: stagnation hours (the `regime.is_stagnation` classifier) are served by the box, advective hours by the Gaussian plume. `disable_regime_dispatch=True` forces pure Gaussian; `backend="stagnation_box"` forces the box for every hour. Box *parameter calibration* is an experiments-repo follow-up (no calibration data in this service repo); v1 defaults are uncalibrated.
- `LagrangianPuffBackend` (stub) — pure-Python CALPUFF-style puff model. ~300 lines to implement; runs in-process; handles non-stationary releases. Issue #1 in the repo.

**Tier 2 — runs as a sibling Railway service, called via `RemoteHTTPBackend`**

- HYSPLIT (the `geodemic` repo's private Docker, when deployed). Provides regulatory-grade output. Higher latency (seconds to tens of seconds), needs ARL meteorology.
- STILT (planned). Receptor-oriented backward Lagrangian, ideal for emission inversion.

**Tier 3 — runs on NRP, results consumed asynchronously**

For workloads that don't fit in a request-response cycle (Sobol sweeps, MCMC). Not a backend in the API sense; a separate dispatch path entirely. Lives in the experiments repo's `nrp/` directory.

## Ensemble dispatcher

The `EnsembleBackend` runs N backends and weight-combines their concentration arrays. Failure of one backend is non-fatal — it's dropped from the combination and weights are renormalized. Per-backend metadata (runtime, max concentration, status) is preserved in `member_results` for diagnostics.

The choice of ensemble *strategy* — fixed weights, regime-conditional weights, stacked footprint inversion — is a calibration question, not a service question. The service provides the dispatcher; the experiments repo decides the weights and which backends to include.

## API contract

All requests are typed via Pydantic models in `schemas.py`. The contract is versioned (`SCHEMA_VERSION` constant); changes to the schema bump the version and require a deprecation cycle.

Endpoints:

- `POST /forward` — forward dispersion. Body: `ForwardRunRequest`. Response: `ForwardRunResult`.
- `POST /inversion` — NNLS emission inversion. Body: `InversionRequest`. Response: `InversionResult`.
- `GET /health` — liveness.

Cache behavior: `/forward` requests are content-addressed by a hash of the canonical request body. Identical inputs → identical outputs → cached. The cache is on local disk (mounted volume on Railway). Cache hits return in < 5 ms.

## Deployment

See `docs/deployment.md` for Railway specifics. The Dockerfile is multi-stage and produces a ~150 MB image. The `railway.json` configures the build, healthcheck, and restart policy. `DISPERSION_CACHE_DIR` selects the cache location (default `/app/.cache`, recommend mounting a volume).

## What's not in this repo

- Calibration runs, parameter fits, sensitivity analyses → `tijuana-dispersion-experiments/experiments/`
- Emissions-model research and parameter-fitting workflows → `tijuana-dispersion-experiments/emissions_research/`
- NRP batch jobs → `tijuana-dispersion-experiments/nrp/`
- Notebooks, exploratory analyses → `tijuana-dispersion-experiments/notebooks/`

The dividing line: anything that *runs the service* lives here. Anything that *uses results from the service* lives in the experiments repo.
