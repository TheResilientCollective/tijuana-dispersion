# Why the web app is in this repo

The plan (`docs/mapinterface_plan.md`) calls for this front end to live in its
own repository, `tijuana-map`. That is still the intended home: this repo's
deploy surface is `main` on Railway, and a Node build does not belong in a
Python service image.

It is committed here because this session could not create the standalone
repository — the GitHub integration returned
`403 Resource not accessible by integration` for org repo creation — and the
work would otherwise have been lost when the session container was reclaimed.

## Extracting it

Once `TheResilientCollective/tijuana-map` exists:

```
git clone <tijuana-map-url> && cd tijuana-map
cp -r ../tijuana-dispersion/web/. .
git add -A && git commit -m "feat: public H2S map for the Tijuana River Valley"
git push -u origin main
```

Then delete `web/` from this repo.

## It does not affect the deployment

`Dockerfile` copies only `pyproject.toml`, `uv.lock`, `README.md` and
`tijuana_dispersion/`, so nothing under `web/` enters the service image. No
deployment file was modified (AGENTS.md rule 4).
