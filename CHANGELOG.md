# Changelog

All notable changes to this project will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Stagnation guardrail (issue #2): new `regime` module with
  `is_stagnation()` classifier (calm-nocturnal regime where the
  Gaussian-plume backends have no skill). `run_forward` now flags
  affected hours.
- `ForwardRunResult` gains `stagnation_flags: list[bool]` (per
  timestep) and `out_of_envelope: bool`; `summary` gains
  `n_stagnation_hours` and `regime`. Additive and backward-compatible
  (defaults parse pre-0.2.0 cached payloads).
- Stagnation box model (issue #3): new `stagnation` module with the
  calm-night accumulation recurrence (`box_series`,
  `StagnationBoxParams`, `H_MIX_BY_STABILITY_M` mixing-depth table) and
  a `StagnationBoxBackend` (receptor-independent v1). `run_forward` now
  performs per-timestep **regime dispatch**: on stagnation hours the
  Gaussian-plume result (which has ~no skill there) is replaced by the
  accumulation box; advective hours stay Gaussian. `summary` gains
  `dispatch` (`regime` | `disabled` | `forced_box`).
- `ForwardRunRequest` gains `disable_regime_dispatch: bool = False`
  (pure-Gaussian ablation / back-compat) and `backend` accepts
  `"stagnation_box"` to force the box for every hour. Additive and
  backward-compatible.

### Changed
- `SCHEMA_VERSION` bumped `0.1.0` → `0.2.0` (issue #2 guardrail) →
  `0.3.0` (issue #3 regime-dispatch fields). All additive.

### Notes
- This builds on the interim honesty guardrail (issue #2): the
  classifier is now also the *dispatch* signal, not just a flag.
- The box's *parameter calibration* (τ, the `H_mix`-by-stability
  table, neighbourhood area, local-emission split) against the 242
  Berry >100 ppb hours is an experiments-repo follow-up — no
  calibration data lives in this service repo. v1 ships
  physically-reasonable but explicitly uncalibrated defaults.
- The 2026-05-15 calm-night reanalysis found the dataset's own
  `stable_atm` flag is a sharper stagnation classifier than
  `is_night & wind<u_calm`, but `stable_atm` is not in
  `MetCondition`/`MetSpec`; folding it in is a documented future
  refinement (Pasquill E/F is the interim proxy used by the box).

## [0.3.0] — 2026-05-05

### Added
- Backend protocol and ensemble dispatcher (`backends.py`): `LocalGaussianPlumeBackend`, `RemoteHTTPBackend`, `LagrangianPuffBackend` stub, `EnsembleBackend` with per-member diagnostics, and `build_default_ensemble()` factory.
- Emissions model skeleton (`emissions.py`): `EmissionDrivers`, `EmissionParameters`, `EmissionsModel`, parametric functions (`f_temperature`, `f_substrate`, `f_volatilization`, `f_diel`), and `make_emissions_model_with_overrides()` for plugging in external implementations.

### Notes
- The puff backend is intentionally a stub. Implementing it is tracked as issue #1.

## [0.2.0] — 2026-05-05

### Added
- `calibration.py`: distributed-source generators, bounded NNLS via `lsq_linear` with archetype priors and smoothness regularization, wind-conditional residual diagnostic.

### Changed
- Cache directory configurable via `DISPERSION_CACHE_DIR` env var.

## [0.1.0] — 2026-05-05

### Added
- Initial dispersion service: Gaussian plume (Briggs rural σ, Pasquill stability), Pydantic API contract, FastAPI app with `/forward`, `/inversion`, `/health`, content-addressed disk cache, Dockerfile and `railway.json`.
