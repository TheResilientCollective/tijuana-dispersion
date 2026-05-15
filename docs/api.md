# API contract

Schemas are defined in `tijuana_dispersion/schemas.py` (Pydantic).
`SCHEMA_VERSION` is the contract version; it follows semver, and the
field travels on every request/result so clients can detect drift.

**Current `SCHEMA_VERSION`: `0.2.0`.**

## Endpoints

The FastAPI app (`tijuana_dispersion/api.py`) exposes:

- `GET  /health` → `{"status": "ok", "schema_version": "..."}`
- `POST /forward` → `ForwardRunResult` (501 if `backend="hysplit"`)
- `POST /inversion` → `InversionResult`

## `ForwardRunRequest`

| field | type | default | notes |
|---|---|---|---|
| `schema_version` | str | `SCHEMA_VERSION` | |
| `backend` | `"gaussian_plume" \| "hysplit"` | `gaussian_plume` | `hysplit` is a stub (501) |
| `sources` | `list[SourceSpec]` | — | |
| `receptors` | `list[ReceptorSpec]` | — | |
| `meteorology` | `list[MetSpec]` | — | one entry per timestep |
| `units` | `"ppb" \| "ugm3"` | `ppb` | |
| `return_per_source` | bool | `false` | 3-D result if true |
| `cache_key` | str \| None | None | content-addressed if omitted |
| `notes` | str \| None | None | |

## `ForwardRunResult`

Standard fields: `backend`, `n_times`, `n_receptors`, `n_sources`,
`units`, `receptor_names`, `timestamps`, `concentrations`
(`[n_times][n_receptors]`, or 3-D if `return_per_source`), `summary`,
`cached`, `runtime_ms`.

### Stagnation guardrail (schema 0.2.0, additive)

The Gaussian-plume backends model **advective** transport. They have
~no skill in the **calm-nocturnal stagnation regime** (H₂S accumulates
locally under a collapsed stable boundary layer; no preferred wind
direction). To avoid presenting a confident low concentration in that
regime, the result carries:

| field | type | meaning |
|---|---|---|
| `stagnation_flags` | `list[bool]` | length `n_times`; `true` where the hour is calm-nocturnal stagnation |
| `out_of_envelope` | bool | `true` if **any** timestep is stagnation |
| `summary.n_stagnation_hours` | int | count of flagged timesteps |
| `summary.regime` | str | `"stagnation"` if `out_of_envelope` else `"advective"` |

**Client guidance:** when `stagnation_flags[t]` is `true`, treat that
timestep's concentration as *unreliable / lower bound only* — the true
value can be 1–2 orders of magnitude higher (observed Berry Elementary
calm-night events reach 150–750 ppb while the plume model predicts
single digits). Do not surface flagged hours as confident estimates in
health-facing contexts.

Classifier: `is_stagnation(met, u_calm=DEFAULT_U_CALM_MS)` in
`tijuana_dispersion/regime.py` — v1 rule is `is_night and
wind_speed_ms < u_calm` (`DEFAULT_U_CALM_MS = 2.5`).

**Backward compatibility:** the two new fields default to `[]` /
`false`, so pre-0.2.0 cached payloads and older clients parse
unchanged. The change is additive; no existing field changed meaning.

### Roadmap

This guardrail only *flags* the regime. A dedicated prediction model
for it (`stagnation_box` backend) is tracked as issue #3 and will
dispatch on this same classifier.

## `InversionRequest` / `InversionResult`

See `schemas.py`. `observations` is `[n_times][n_receptors]` with
`null` for missing. Result carries `fitted_rates_g_s`, `source_names`,
`residual_rms`, `fit_diagnostics`.
