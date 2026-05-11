# Railway Deployment Guide

## What you're deploying

The `dispersion_service/` directory is a self-contained FastAPI app with a Dockerfile and a `railway.json`. Pushing it to Railway gives you a public HTTPS URL that exposes `/forward`, `/inversion`, and `/health` endpoints. The service is small (~150 MB image, sub-100 ms requests) and fits comfortably on Railway's hobby tier.

## What's in the deploy bundle

```
dispersion_service/
├── Dockerfile               # multi-stage slim build
├── railway.json             # Railway config (Dockerfile builder, healthcheck)
├── requirements.txt         # pinned: fastapi, uvicorn, pydantic, numpy, scipy
├── .dockerignore
└── tijuana_dispersion/      # the package
    ├── __init__.py
    ├── core.py              # Gaussian plume physics
    ├── schemas.py           # API contract
    ├── service.py           # dispatch + cache + NNLS inversion
    ├── calibration.py       # bounded inversion, distributed sources, diagnostics
    └── api.py               # FastAPI app
```

## Steps (CLI path — fastest)

Install the Railway CLI if you don't have it:

```
brew install railwayapp/railway/railway          # macOS
curl -fsSL https://railway.com/install.sh | sh   # Linux
```

From the `dispersion_service/` directory:

```
railway login
railway link                                 # pick your project, or create a new one
railway up                                    # builds the Dockerfile, deploys
```

That's it. After the build finishes (~3 minutes for the first deploy), Railway prints a service URL. Generate a public domain:

```
railway domain
```

You'll get something like `tijuana-dispersion-production.up.railway.app`. Test it:

```
curl https://your-service.up.railway.app/health
# {"status":"ok","schema_version":"0.1.0"}
```

## Steps (web path — if you prefer the UI)

Push the `dispersion_service/` directory to a GitHub repo. In the Railway dashboard, **New Project → Deploy from GitHub Repo**, pick the repo. Railway auto-detects the Dockerfile and builds. Hit "Generate Domain" in service settings.

## Persistent cache volume (recommended)

Forward-run results are cached on disk by content hash. Without a volume, the cache dies on every deploy. Mount one:

In the Railway dashboard for the service, **Settings → Volumes → New Volume**, mount path `/app/.cache`. The container already reads `DISPERSION_CACHE_DIR` from env (default is `/app/.cache`), so no code change is needed. A 1 GB volume is plenty for thousands of cached forward runs.

## Environment variables

None required. Optional:

- `DISPERSION_CACHE_DIR` — override cache directory (default `/app/.cache`)
- `PORT` — Railway sets this automatically; the Dockerfile honors it

## Calling the service from Claude (or anywhere)

Once deployed, every request is a simple POST. Example forward run:

```bash
curl -X POST https://your-service.up.railway.app/forward \
  -H "Content-Type: application/json" \
  -d @example_request.json
```

Where `example_request.json` follows the `ForwardRunRequest` schema in `tijuana_dispersion/schemas.py`. From a Claude session, you can call this via `web_fetch` with `method=POST` and a JSON body. The service contract is versioned (`SCHEMA_VERSION` in `schemas.py`), so a future MCP wrapper can target the same endpoints.

## Resource sizing

The current Gaussian plume backend has tiny resource needs:
- Cold start: <1 second
- Memory at idle: ~80 MB
- Memory under load (72-hour, 38-source request): ~120 MB
- Per-request CPU: <100 ms
- Cache hit: <5 ms

Hobby plan (8 GB RAM, shared vCPU) is enormously over-provisioned for the Gaussian backend. The hobby plan becomes relevant once you add a Lagrangian puff or STILT-equivalent backend (see docker_dispersion_models.md).

## What to do after first deploy

1. **Smoke test**: `curl /health`, then run `demo_run.py` with the URL substituted into the service base.
2. **Add a volume** for persistent caching (if you'll be iterating).
3. **Note the URL** — when you check in, just send "the service is at `https://...`" and the next session can call it directly via `web_fetch`.

## Troubleshooting

- Build fails on `pip install`: usually a transient PyPI issue; `railway up` again.
- Healthcheck fails: check that `$PORT` env var is being respected. The Dockerfile uses `${PORT}` in the CMD.
- Cold-start times longer than expected: Railway's free tier sleeps; upgrade to hobby ($5/mo) for always-on.

## Updating the service

After code changes in `dispersion_service/`, just re-run `railway up`. Or push to the GitHub-linked branch if you set up the repo path. Each deploy gets a unique URL until promoted.
