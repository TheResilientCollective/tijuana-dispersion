# Wire HYSPLIT remote backend to private Docker

## Why

The Resilient Collective has a private HYSPLIT Docker container that should serve as a high-fidelity backend for the dispersion service. The `RemoteHTTPBackend` in `backends.py` is a generic HTTP client; this issue wires it to the specific HYSPLIT service.

## Scope

1. Deploy the HYSPLIT Docker container as a Railway sibling service in the same project as `tijuana-dispersion`. Internal-only (no public domain); accessed by the main service over Railway's private networking.

2. Verify that the HYSPLIT service speaks the same `ForwardRunRequest` / `ForwardRunResult` schema. If not, write an adapter shim in the HYSPLIT service that translates the request format.

3. Configure the main service's `EnsembleBackend` to include the HYSPLIT backend with an initial weight of 0.3 (Gaussian plume 0.4, puff 0.3, HYSPLIT 0.3 once both other backends are in place).

4. Add an integration test that runs a small forward request through the ensemble and verifies all three backends contributed sensibly.

## Acceptance criteria

- [ ] HYSPLIT service deploys to Railway and `curl http://hysplit.railway.internal/health` returns 200.
- [ ] Main service can call the HYSPLIT backend via `RemoteHTTPBackend` for a single forward run.
- [ ] Ensemble call with all three backends returns a concentration array; per-backend metadata in `member_results` shows all three OK.
- [ ] If HYSPLIT service is down, the ensemble degrades gracefully (warning logged, weights renormalized).

## Things to figure out

- ARL meteorological data: where does HYSPLIT get them on Railway? Options include a mounted Railway volume populated by a cron sidecar that fetches HRRR from NOMADS, or fetching on-demand per request (slower but simpler).
- Authentication between main service and HYSPLIT service. Suggest a shared bearer token in Railway secrets.
- Result caching: HYSPLIT results should be cached aggressively because runs are expensive. The cache key needs to include the HYSPLIT-specific configuration (e.g., trajectory length, resolution).

## Estimated effort

Two to three days. Most of the time is in HYSPLIT-side configuration, not the wiring.
