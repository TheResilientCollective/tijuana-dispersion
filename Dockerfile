# Tijuana H2S Dispersion Service
# Slim multi-stage build, ~150 MB final image.
# Designed for Railway free/hobby tiers (512 MB RAM, 1 vCPU).
#
# Dependency management uses uv + pyproject.toml. The lockfile (uv.lock)
# is committed and consumed at build time for reproducible installs.

FROM python:3.12-slim AS builder

# Native-wheel build deps (numpy, scipy if no manylinux wheels available)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Build at the same path that the runtime stage will use so the venv's
# script shebangs (e.g. `#!/app/.venv/bin/python3.12`) resolve after the
# stage copy. uv venvs are not relocatable by default.
WORKDIR /app

# Install deps in one layer (cached on dep changes only)
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Then install the project itself
COPY tijuana_dispersion ./tijuana_dispersion
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime stage ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring over the venv from the builder. Same path → shebangs still resolve.
COPY --from=builder /app/.venv /app/.venv
# Bring over the project code too — pyproject + uv.lock are not needed at
# runtime, but the package itself is imported by uvicorn.
COPY --from=builder /app/tijuana_dispersion /app/tijuana_dispersion

# Cache directory for dispersion results (mount a Railway volume here in prod)
RUN mkdir -p /app/.cache

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DISPERSION_CACHE_DIR=/app/.cache \
    PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Single uvicorn worker — our requests are CPU-bound and short.
# Bump to 2 workers if Railway plan provides 1+ vCPU.
CMD ["sh", "-c", "uvicorn tijuana_dispersion.api:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]
