# Docker-Deployable Dispersion Models — Survey & Recommendations

## The constraint

Railway hobby tier: 8 GB RAM, shared vCPU, ephemeral disk + optional volumes, image size practically capped around 4 GB. Long-running container fine. No GPU. Outbound network is unrestricted, which matters for any model that needs to fetch met data.

For our scale (a few km between sources and receptors, hourly time-step, three receptors), most large-scale atmospheric chemistry models are wildly over-spec'd. The shortlist below is sorted by deployability on Railway specifically.

## Tier 1 — runs on Railway directly

### Pure-Python Lagrangian puff (recommended next addition)

**Status**: not yet built; one weekend of work
**Image size**: ~150 MB
**Memory**: <500 MB even for 1000 puffs
**Met data**: uses our existing hourly meteorology — no external files

The natural successor to Gaussian plume. Emissions are released as discrete Gaussian puffs every timestep; each puff is advected by the current wind and grows by σ ∝ √t. Concentration at a receptor is the sum over all active puffs. This is what CALPUFF does in Fortran; we'd implement in numpy. Captures non-stationary releases (spills) and time-varying winds correctly, where Gaussian plume cannot. Same algorithmic complexity class as our existing code, similar runtime.

This is the single highest-value addition because it removes the steady-state assumption that breaks during transient events — exactly the events that drive exceedances.

### GRAL (Graz Lagrangian)

**Status**: open source, has Linux builds, Docker not official but easy to wrap
**Image size**: ~200-400 MB depending on dependencies
**Memory**: a few hundred MB
**Met data**: needs hourly profiles, comparable to what we already have

GRAL is a microscale Lagrangian model built for street-canyon and small-domain dispersion. The Austrian government uses it for regulatory work in complex terrain (hills, urban). Our valley topography is exactly the kind of complex-terrain case GRAL was designed for. C# / .NET runtime is awkward but containerizable. Less mainstream than HYSPLIT in the US, more mainstream in Europe.

If we want a third-party validation model that runs on Railway directly, GRAL is the option.

## Tier 2 — separate compute, called over REST

These are the right choice for higher-fidelity work, but they want more resources than Railway is comfortable providing. Deploy them on a single Hetzner CX32 (~$8/mo, 8 GB RAM, dedicated vCPUs) and have the Railway-hosted FastAPI service route `backend="hysplit"` requests there.

### STILT (Stochastic Time-Inverted Lagrangian Transport) — top recommendation for inversion

**Image**: `uataq/stilt-docker` on Docker Hub (active, well-maintained)
**Image size**: ~3 GB with dependencies
**Memory**: 2-4 GB per backward run
**Met data**: HRRR or NAM ARL files via the included downloader

STILT is purpose-built for receptor-oriented emission inversion. It runs *backward* particle trajectories from each receptor, producing a footprint matrix that maps emissions at each grid cell to concentration at the receptor — which is exactly the matrix our NNLS inversion needs as input. Output formats are NetCDF that pandas/xarray can read directly.

The University of Utah maintains the docker container actively (https://github.com/uataq/stilt). It's the best fit for this project's existing methodology. The trade-off is meteorological data: STILT wants ARL-format met files (HRRR is 3 km, available from NOMADS). Storage for one month of 3 km HRRR is ~20 GB.

### FLEXPART

**Image**: `flexpart/flexpart` and several community images
**Image size**: 1-3 GB
**Memory**: 1-2 GB
**Met data**: ECMWF or NCEP, similar storage to STILT

The most mature Lagrangian particle dispersion model in the field. Pure Fortran, used worldwide for nuclear accident response, volcanic plume tracking, emission inversions. Has both forward and backward modes. A Python wrapper exists (`flexpart-pp`). Slightly heavier setup than STILT and less specifically tailored for emission inversion, but it's the Cadillac of Lagrangian models if STILT's R-bias is a problem.

### HYSPLIT — the regulatory standard

**Image**: `noaa/hysplit` on Docker Hub (official NOAA)
**Image size**: ~2 GB
**Memory**: 1-2 GB
**Met data**: ARL format (HRRR, NAM, GFS)

HYSPLIT is what regulatory agencies expect to see. NOAA maintains the official container at https://hub.docker.com/r/noaa/hysplit. Less specialized than STILT for emission inversion, but better-known in air quality circles and ideal for any analysis whose audience includes USIBWC, EPA, or the County. The container is workmanlike — it does what it says, with the trade-off that the CONTROL file format is finicky.

## Tier 3 — not worth the trouble for this project

CMAQ, CAM-Chem, GEOS-Chem, WRF-Chem are regional/global chemistry-transport models. Excellent science, vastly over-spec'd for a 10 km × 10 km domain. AERMOD is the EPA short-range regulatory model but its Linux ecosystem is thinner than HYSPLIT's and the gain over Gaussian plume is small at our scale. CALPUFF is similar — historically important, but the open-source ecosystem has migrated to CALPUFF clones in Python.

## Concrete recommendation

Three-stage rollout:

1. **Now (Railway, free tier)**: Deploy the existing Gaussian plume service. Iterate on calibration. The improvements from v2 (distributed sources, archetype priors, wind diagnostics) account for most of the gains a more sophisticated model would deliver.

2. **Next (still Railway)**: Add the pure-Python Lagrangian puff backend. Selectable via `backend="puff"` on existing requests, no infrastructure change. This handles non-stationary releases (spills) properly, which Gaussian plume cannot.

3. **Later (separate Hetzner VM)**: Deploy STILT as a sibling service. Call from Railway via REST when `backend="stilt"` is requested. Use it for monthly footprint recomputation and event-attribution validation, not for interactive calibration loops.

HYSPLIT slots in at the same place as STILT — same VM, same routing logic in the FastAPI service, just a different `backend` value. If you have an existing HYSPLIT setup, it's easier to port that than to learn STILT. If you're starting fresh and the work is emission inversion, STILT is the better tool.

## What this means concretely for the next session

When you check in, the conversation is: "Railway is up at `https://...`. Build the puff backend." That's a 1-2 day task and produces a fully Railway-hosted, two-backend dispersion service that handles both steady-state plumes and transient puffs. STILT/HYSPLIT can wait until either (a) we hit a calibration regime where Gaussian-plus-puff genuinely doesn't suffice, or (b) we need regulatory-format outputs.
