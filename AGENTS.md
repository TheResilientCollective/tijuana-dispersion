# AGENTS.md — `tijuana-dispersion` service repository

This file is the operating manual for any AI coding agent (Claude Code, Cursor, Copilot, etc.) working in this repository. Read it in full at the start of every session. The rules in this file supersede any contradicting habits or training defaults the agent might have.

## What this repo is

A FastAPI service that performs atmospheric dispersion modeling for H₂S emissions in the Tijuana River Valley. Deployed to Railway. Called by both an interactive web UI and batch calibration runs from the `tijuana-dispersion-experiments` repo. The service is **small, stable, and deployable**. Deployment surface is `main`. Every merge to `main` may trigger a Railway redeploy.

This repo does **not** contain calibration scripts, notebooks, or experiment outputs. Those live in `tijuana-dispersion-experiments`. If you are tempted to add an experiment script here, stop — it goes in the other repo.

## Skills installed for this repo

- **`dignified-python@dagster-skills`** — modern Python coding standards. Read at session start.

The Dagster expert skill is **not** for this repo.

## Hard rules (violations break the build, on purpose)

### 1. No synthetic, mock, or placeholder data outside `tests/`

Functions in `tijuana_dispersion/` must never fabricate data when real data is missing. If an input is `None`, missing, or invalid, raise an exception with a clear message. Never silently substitute zeros, random values, or "reasonable defaults." This rule exists because silent fakes corrupt downstream calibration runs in ways that are nearly impossible to debug after the fact.

Allowed exceptions: unit tests in `tests/` may use synthetic fixtures freely. Mark them clearly (`SYNTHETIC_FIXTURE_*` constants, `pytest.fixture` named `synthetic_*`, etc.) so the boundary is explicit.

CI enforces this with a custom check that flags `np.random` calls, `random.*` calls, and obvious placeholder patterns (`return 0.0  # placeholder`, `mock_` prefixes) outside of `tests/`. If your code legitimately needs randomness in production (it usually doesn't here), document why in a code comment with the format `# random ok: <reason>` and the check will pass.

### 2. No secrets in source

No API keys, no passwords, no tokens, no `.env` files in commits. The pre-commit hook runs `detect-secrets` and CI re-runs it. If you need a value at runtime, read it from `os.environ` and document the variable in `.env.example` (with a placeholder, never the real value).

### 3. No data files in git

Anything over 1 MB does not belong in this repo. There is no calibration data, observation files, or model outputs in this repo at all. The package depends only on its own code and what callers provide via the API.

### 4. No `Dockerfile`, `requirements.txt`, `pyproject.toml`, `railway.json`, or `.github/` changes without an explicit instruction

These files affect deployment and require human review. Open a PR but do not merge. Do not add new top-level dependencies on your own initiative — propose them in the PR description and wait for approval.

### 5. Parquet preferred over CSV

When reading data files (rare in this repo, but possible), prefer parquet. The H₂S parquet uses timezone-aware `datetime64[ns, America/Los_Angeles]` indices natively; CSV requires explicit `pd.to_datetime(..., utc=True).dt.tz_convert('America/Los_Angeles')`. Don't lose timezone information in round-trips.

## Development workflow

### At session start

1. `git pull` on the current branch.
2. Read `CHANGELOG.md` under `## [Unreleased]` to see what's in flight.
3. Read this file (yes, every session).
4. Check open issues with `gh issue list` if you don't know what task to pick up.

### Per-task workflow

1. Create a feature branch: `git checkout -b feat/<short-description>` or `fix/<short>`.
2. Write tests **first** when adding new functionality to `core.py`, `schemas.py`, `service.py`, or `backends.py`. Physics bugs are silent; tests are how we catch them.
3. Implement.
4. Run pre-commit locally: `pre-commit run --all-files`.
5. Run the full test suite: `pytest`. Run `mypy --strict tijuana_dispersion`.
6. Update `CHANGELOG.md` under `## [Unreleased]` with a one-line description.
7. Commit with a [conventional commit](https://www.conventionalcommits.org/) message.
8. Push the branch and open a PR with `gh pr create`.

### Per-commit hygiene

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `perf:`, `style:`. Each commit tells one story; no "WIP" or "fixes" commits in PRs that target `main`.
- Never `--force-push` to a shared branch. Only force-push to your own feature branch, and only if you must.

### PR requirements

Every PR into `main` must:

1. Have green CI (lint + format + types + tests + Docker build).
2. Have an explicit human approval. **Auto-merge is disabled in this repo.** You may use `gh pr ready` to mark the PR ready for review, but you do not merge it yourself.
3. Reference an issue when applicable (`Closes #N`).
4. Describe the change in 2-5 sentences. If the change touches dispersion physics or the API contract, describe what was tested and what wasn't.

If you genuinely cannot proceed without information from the human, open the PR as a draft (`gh pr create --draft`) with the question in the description and stop work on that branch.

## Code quality (enforced by CI)

| Tool | Command | Failure mode |
|---|---|---|
| ruff format | `ruff format --check .` | CI fails |
| ruff check | `ruff check .` | CI fails on errors |
| mypy strict | `mypy --strict tijuana_dispersion` | CI fails |
| pytest | `pytest --cov=tijuana_dispersion --cov-fail-under=80` | CI fails if coverage drops below 80% on `core.py` and `schemas.py` |
| docker build | `docker build .` | CI fails |
| detect-secrets | pre-commit + CI | CI fails on detection |

The 80% coverage floor applies to `core.py` and `schemas.py` specifically because dispersion physics bugs and contract bugs are silent. Other modules have no coverage floor but are expected to grow with their feature surface.

## Style points the linters can't catch

- **Numpy-style docstrings** for every public function and class. Don't write Google-style or RST.
- **No bare `except:`**. Catch specific exceptions; if you must catch everything, use `except Exception as e:` and re-raise or log with context.
- **No `print()`** in package code. Use the standard `logging` module with `logger = logging.getLogger(__name__)`.
- **Type hints on every signature** in package code. The `dignified-python` skill covers modern type syntax (use `list[str]` not `List[str]`, `str | None` not `Optional[str]`, etc.).
- **No `assert` for runtime checks.** Asserts are stripped under `python -O` and become silent. Use `raise ValueError(...)` for input validation.

## Architecture pointers

If you are modifying behavior, read the relevant doc first.

- `docs/architecture.md` — overall system shape, backend tiers, ensemble dispatcher
- `docs/api.md` — request/response contracts, schema versioning, MCP wrapper plan
- `docs/deployment.md` — Railway specifics, container details, healthcheck

The package is structured as:

```
tijuana_dispersion/
├── core.py          # Gaussian plume physics
├── schemas.py       # Pydantic API contract
├── service.py       # FastAPI dispatch + content-addressed cache
├── calibration.py   # Distributed sources, bounded NNLS, wind diagnostics
├── backends.py      # Backend protocol, ensemble dispatcher
├── emissions.py     # Emissions model skeleton + bridge points
└── api.py           # FastAPI app
```

Keep modules at the responsibilities listed. If you find yourself adding NNLS code to `core.py` or dispersion code to `calibration.py`, stop and reconsider.

## Things that look like edge cases but aren't

- **Wind direction is "from" in meteorological convention**, measured CW from north. The rotation in `core.py` is correct. Resist the urge to "fix" it.
- **The cache is content-addressed by request hash**, not by timestamp. Two requests with the same inputs return the same cached result. This is intentional — calibration loops issue many duplicate forward calls.
- **The HYSPLIT backend stub raises `NotImplementedError`** on purpose. Do not change this to a silent fallback.

## When in doubt

- Open an issue with the question. Don't guess.
- If the question is small and the answer is obvious, document the decision in a code comment so the next session sees it.
- If a previous session made a decision you'd reverse, look at the commit history before reverting. There may have been a reason.
