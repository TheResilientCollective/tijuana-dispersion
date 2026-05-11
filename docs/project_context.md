# Project Context

This document is the orientation for someone (human or agent) joining the project who needs to know what we're doing scientifically before they touch code.

## The problem

The Tijuana River Valley sits on the US-Mexico border in San Diego County. Untreated and partially-treated sewage from Tijuana flows north across the border into the Tijuana River, into the Tijuana Estuary, and out into the Pacific. When this sewage encounters anaerobic conditions in the river channel and estuary mudflats, sulfate-reducing bacteria produce hydrogen sulfide (H₂S), which volatilizes into the atmosphere and produces severe odor episodes affecting communities including Imperial Beach, Nestor, and San Ysidro.

H₂S is detectable by smell at concentrations as low as ~0.5 ppb. Concentrations during severe episodes routinely exceed 100 ppb at monitoring stations. The odor disrupts daily life for thousands of residents, with health effects ranging from headaches and nausea to respiratory and neurological complaints.

## The monitoring network

Three SDAPCD continuous H₂S monitors, all 1-minute resolution, aggregated to 15-min and hourly for analysis:

| Station | ID | Location | Notes |
|---|---|---|---|
| NESTOR-BES | NESTOR_BES | 32.567097, -117.090656 | Berry Elementary School; central, between channel and estuary |
| IB CIVIC CTR | IB_CIVIC_CTR | 32.576139, -117.115361 | Western station; closest to estuary |
| SAN YSIDRO | SAN_YSIDRO | 32.552794, -117.047286 | Eastern station; closest to border crossing |

The three stations triangulate the channel-estuary-bay complex. Each captures a different mix of source contributions depending on wind direction.

## The 17 named emission sources

Hydrologically and anatomically distinct emission points along the river system. From east to west, roughly:

- **Border drains** (sulfate-rich, sewage-loaded, nocturnally peaked): Stewart's Drain, Smuggler's Gulch, Goat Canyon, Hollister St PS, Del Sol Canyon, Silva Drain
- **Mid-channel** (diffuse, depends on standing water): Saturn Blvd Bridge, Hollister Bridges, Dairy Mart Bridge
- **Cross-border crossings** (high-flow events): Tijuana River Crossing CDLP W/E
- **Estuary** (mudflat emissions, tidal): Oneonta Slough Near IB, Tijuana River Beach Outlet
- **Bay** (background, low): San Diego Bay Otay River outlet, Fruitdale ponds

Lat/lons for each are in `data/emission_sources.json`. Beyond these 17, there are clearly additional distributed sources along the channel and across the estuary mudflats; calibration v2 added ~21 distributed sources to capture them.

## What we've established (project memory)

Findings carried forward from prior work in the project:

1. **SBIWTP flow inversely predicts H₂S.** When the South Bay International Wastewater Treatment Plant processes more sewage, less reaches the river and emissions drop (r = -0.47 at NESTOR with 1-day lag). The compound effect of low SBIWTP throughput + warm temperatures produces extreme H₂S concentrations.

2. **Three-source attribution is real.** East (border crossings), West (estuary/pump station), South (cross-border discharge) have geographically distinct centers of mass confirmed across multiple analyses.

3. **Threshold analysis.** Resident odor complaints begin appearing around 2 ppb, cross 50% probability near 8-10 ppb, reach 76% likelihood at 15-20 ppb, near-certain above 50 ppb. PR-AUC peaks at 30 ppb — the strongest early-warning tier for operational alerting.

4. **Extreme events are nearly exclusively nocturnal** (98%), peak March-May, strongly associated with calm winds, elevated humidity, and SBIWTP flow deficits.

5. **22.8%+ of days since January 2024** have exceeded 30 ppb at at least one station. March 2026 reached 83% of days. The scale of the public health burden is large.

6. **PurpleAir data is not a useful H₂S proxy** at these sites. The Bosch VOC sensor appears to be suppressed by sulfur-compound cross-sensitivity.

7. **Dispersion physics is roughly right.** The Gaussian plume backend, when given correctly-located sources and physically-bounded rates, captures the timing of nocturnal peaks at NESTOR with r=0.6+. Failures are in source attribution and emission parameterization, not in the dispersion equations themselves.

## The modeling task

Given continuous observations at three receptors plus meteorology and SBIWTP flow data, infer the time-varying emission rates at distributed sources well enough to:

- **Operationally**: forecast 0-72h H₂S concentrations at each receptor with quantified uncertainty.
- **Scientifically**: attribute observed concentrations to specific source archetypes (Stewart's Drain vs Smuggler's Gulch vs estuary vs etc.) for accountability and policy.
- **Episodically**: reconstruct the magnitude and source of documented spill events (Stewart's Drain Feb 10 and Mar 14-15 2026; Smuggler's Gulch Dec 2 2025).

## What's hard

The forward dispersion problem is straightforward at our scale; the *inverse* problem is genuinely underdetermined. With 38 candidate sources and 3 receptors, point-estimate calibration fits anything. The current approach (process-based emissions model + bounded NNLS + ensemble of dispersion backends) is the best path we've found to a determined system; whether it works at the level needed for operational decisions remains to be confirmed against a proper holdout.

## What this code does

The two repos together implement:

- **`tijuana-dispersion`**: forward dispersion service with multiple backends (Gaussian plume, puff, HYSPLIT), source-receptor matrix construction, NNLS-based emission inversion, FastAPI HTTP service, Railway deployment.
- **`tijuana-dispersion-experiments`**: emissions-model research, calibration experiments, NRP/Argo workflows for compute-rich calibration (Sobol sensitivity, MCMC, leave-one-event-out CV), notebooks for exploration.

Together they support: a Railway-hosted always-on service for operational use; an NRP-hosted batch-processing capability for proper calibration; a clean separation between deployable code and research churn.

## Where to start

1. Read this document.
2. Read [`AGENTS.md`](../AGENTS.md) for the rules.
3. Run `make check` to confirm your environment works.
4. Pick an open issue.
