# Trajectory & Concentration Models on Railway — Plan

Written 2026-05-05. Picks up from `docker_dispersion_models.md` with a sharper focus on Railway-deployability and ensembling.

## What "Railway-deployable" means in practice

Railway's hobby plan gives you 8 GB RAM, shared vCPU, ephemeral disk plus volumes, ~4 GB practical image-size ceiling, no GPU, and unlimited outbound network. Anything that fits in that envelope and doesn't require GBs of pre-staged meteorological data on local disk is fair game. Everything else either runs on a separate Hetzner VM and gets called from the Railway service, or needs a different deployment story.

## Candidate models — narrow list

The previous survey covered the broad landscape. Here is the list pruned to what's actually worth deploying for *this* project, with explicit Railway suitability.

### Already-built, runs on Railway today

**Gaussian plume** (in `tijuana_dispersion/core.py`). Pure numpy, sub-100 ms, 80 MB resident memory, no external dependencies. Steady-state assumption is the limitation; great for stable nocturnal regimes, breaks during transient spill events.

### Build on top of what's there (one-weekend work each)

**Lagrangian puff** (CALPUFF-style, pure Python). Releases discrete Gaussian puffs that get advected by hourly wind and disperse as σ ∝ √t. Same complexity class as the plume code, ~300 lines. Captures non-stationarity. Fits on Railway free tier. Best next addition if we want fidelity for spill events without leaving Railway.

**Lagrangian particle** (custom, in numpy). Release N particles per source per timestep, advect with wind plus turbulent random walk, accumulate concentration in receptor-centered cells. ~500 lines. Slower than puff (depends on N particles), but more flexible — handles non-Gaussian dispersion (skewed plumes under stable conditions), can be vectorized in numpy with reasonable performance. Fits on Railway hobby tier. Comparable to a stripped-down FLEXPART, custom-fit to our scale.

### Your private Docker (HYSPLIT-flavored)

**Deploy as a Railway service alongside the Gaussian plume service.** Two services, same project. The Gaussian plume service handles fast iteration; the HYSPLIT service handles cases where regulatory parity matters or where the puff/particle backends disagree with each other. Wiring is straightforward: the existing `service.py` already has a stub for `backend="hysplit"` that raises NotImplementedError. Replace with an HTTP call to the HYSPLIT service.

The Railway-side concern with HYSPLIT is meteorological data. ARL files for HRRR are ~100 MB per day per region — manageable as a mounted volume that gets refreshed by a cron job. The Docker image itself is ~2 GB, fits comfortably.

### Worth deploying as a Railway sibling, if/when

**STILT** (`uataq/stilt-docker`, ~3 GB image). Backward Lagrangian, designed specifically for the kind of receptor-oriented emission inversion this project is doing. Output is footprint matrices in netCDF — natural input to the existing NNLS inversion. R-primary historically but the Docker container exposes the workflow as CLI. Runs comfortably on Railway hobby tier ($5/month) given 8 GB RAM. Met data is the same HRRR/NAM ARL story.

**FLEXPART** (community Docker images, ~2-3 GB). Alternative to HYSPLIT, better-known in the European emission inversion community. Less specifically tailored for source-receptor matrix inversion than STILT, but more mature than HYSPLIT for backward runs.

**GRAL** (Graz Lagrangian Model). C# / .NET, ~500 MB image. Open source, designed for complex-terrain microscale dispersion. The Tijuana valley topography is exactly its sweet spot — it handles the kind of channeled flow and stagnation regions that flat-surface Gaussian models miss entirely. Less mainstream in the US air quality community but mathematically appropriate for our site.

### Not worth the trouble

CMAQ, GEOS-Chem, WRF-Chem, CAM-Chem, AERMOD. Either too heavy for the domain or too narrow in capability gain over what we'd already have.

## Ensemble strategy

The argument for ensembling is not "more models is better." It's that different models systematically err in different ways, and we can use those error patterns as information.

**Where each model is genuinely best:**

| Regime | Best model | Why |
|---|---|---|
| Steady wind, well-mixed | Gaussian plume | Steady-state assumption holds; fast |
| Calm, nocturnal stable | Lagrangian particle | Captures meandering plume that Gaussian smooths over |
| Spill event, short duration | Lagrangian puff | Transient releases done correctly |
| Complex terrain channeling | GRAL or HYSPLIT | Resolves valley flow |
| Receptor-side inversion | STILT | Backward footprints natively |
| Regulatory deliverable | HYSPLIT or AERMOD | Audit and precedent |

**Three concrete ensemble approaches**, in increasing order of complexity:

### 1. Simple weighted mean (start here)

Fixed weights per model, possibly per receptor. Compute `C_ensemble = Σ w_k × C_k` where weights sum to 1. Tune weights by holdout-set RMS minimization. Cheap, transparent, audit-able. Good first step.

### 2. Regime-conditional weighting

Bin meteorology and time-of-day into regimes (calm-nocturnal, breezy-day, spill-window, etc.) and learn per-regime weights. The Gaussian plume gets weight 0.7 in calm-nocturnal but 0.2 during spill events; Lagrangian puff gets weight 0.6 during spill events. This is what aviation weather forecasters do for ensemble post-processing. Trains in seconds on historical data; predicts in microseconds.

### 3. Stacked footprint inversion

For inversion specifically, *combine* the source-receptor footprint matrices from all models into a single tall matrix and solve one bounded NNLS. This treats every model's prediction as an independent constraint on the underlying emissions. The fitted rates are simultaneously consistent with all models. Computationally identical to the single-model case but with N times more rows in the matrix; still easily solved by `lsq_linear`.

**Recommended path:** start with #1 (one weekend), instrument it well so we can see per-model residuals on every observation, and let the data tell us whether we need #2. Skip #3 for now — it's a research project unto itself and the value over a weighted ensemble is unclear at our scale.

### What models go in the first ensemble?

Honest minimum: Gaussian plume + Lagrangian puff + your HYSPLIT Docker. Three models, three different physics regimes, all deployable on Railway. Build a simple weighted-mean ensemble first; add STILT or FLEXPART later if the residuals point at gaps the first three can't fill.

The key implementation principle: every model returns the same `ForwardRunResult` schema, so the ensemble dispatcher is just a `for backend in backends: results.append(run(backend, req))` plus a weighted combiner. The work is the wiring, not the science.

## Concrete deployment plan on Railway

A single Railway *project* with multiple *services*:

1. **`dispersion-api`** — FastAPI app (current), Gaussian plume + Lagrangian puff in-process. Public domain. Front-door for all requests.
2. **`dispersion-hysplit`** — Your private Docker, internal-only, HTTP API. Called by `dispersion-api` when `backend="hysplit"` or as part of an ensemble.
3. **`dispersion-stilt`** (later) — STILT Docker, internal-only, called for footprint generation.

Internal communication uses Railway's private networking (free, fast). Only `dispersion-api` is publicly reachable. The cache layer on `dispersion-api` deduplicates ensemble runs across all backends — if the same met + sources have been computed, the cached result returns immediately.

Volumes:
- `dispersion-api`: small cache volume (1 GB)
- `dispersion-hysplit`: ARL met data volume (10-50 GB depending on how much history you keep), refreshed by a cron sidecar
- `dispersion-stilt`: same met data, possibly a shared volume if Railway supports it; if not, mirrored

The total Railway monthly cost is low — small services, modest storage, all on hobby plan: probably under $20/month for the full three-service stack.

## What this means for the next session

Three things become deliverable in tight order, each ~1-2 days:

1. **Backend protocol + ensemble dispatcher** in the package (skeleton in `backends.py` already written this session). Wire Gaussian plume and a stub HYSPLIT remote backend. Smoke test the ensemble combiner.
2. **Lagrangian puff backend** in pure Python. Slot into the protocol, call from ensemble.
3. **Your HYSPLIT Docker → Railway service.** Deploy as a sibling service, wire the HTTP backend.

After that, calibration moves to v3 with three backends in the ensemble. Add STILT later if needed.
