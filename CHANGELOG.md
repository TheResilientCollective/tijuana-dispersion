# Changelog

All notable changes to this project will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
