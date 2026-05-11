# tijuana-dispersion

Atmospheric H₂S dispersion modeling service for the Tijuana River Valley.

A FastAPI app exposing forward dispersion and emission inversion as HTTP endpoints. Backends include a built-in Gaussian plume model, an ensemble dispatcher, and (planned) hooks for HYSPLIT, STILT, and a pure-Python Lagrangian puff backend.

Deployed on Railway at `https://tijuana-dispersion-production.up.railway.app` (or wherever your deploy lands).

## Quick start

```
uv sync
uv run pytest
uv run uvicorn tijuana_dispersion.api:app --reload
```

`/health` returns `{"status": "ok", "schema_version": "0.1.0"}`. `/forward` accepts a JSON body matching `ForwardRunRequest` in `tijuana_dispersion/schemas.py`.

## Where things are

- `tijuana_dispersion/` — the Python package
- `tests/` — pytest suite, ≥80% coverage on `core.py` and `schemas.py`
- `docs/architecture.md` — backend tiers, ensemble design, deployment shape
- `docs/api.md` — request/response contracts
- `docs/deployment.md` — Railway specifics
- `Dockerfile`, `railway.json` — deployment config

## For AI coding agents

Read `AGENTS.md` at the start of every session. Hard rules: no synthetic data outside `tests/`, no secrets in source, no data files in git, prefer parquet over CSV, all PRs into `main` need human approval.

## License

MIT. See `LICENSE`.

## Companion repo

Calibration runs, sensitivity analyses, and NRP batch jobs live in [`tijuana-dispersion-experiments`](https://github.com/theresilientcollective/tijuana-dispersion-experiments).
