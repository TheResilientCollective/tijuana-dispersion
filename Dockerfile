# Tijuana H2S Dispersion Service
# Slim multi-stage build, ~150 MB final image.
# Designed for Railway free/hobby tiers (512 MB RAM, 1 vCPU).
#
# Dependency management uses uv + pyproject.toml. The lockfile (uv.lock)
# is committed and consumed at build time for reproducible installs.

FROM python:3.12-slim AS builder

# Install uv (fast Python package manager) and build deps for native wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /build

# Install dependencies in a separate layer for better caching.
# --no-install-project: install deps only, not the local package itself.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Now install the package itself
COPY tijuana_dispersion ./tijuana_dispersion
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime stage ----
FROM python:3.12-slim

# Just runtime essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pull the venv from the builder — already includes the package and its deps
COPY --from=builder /build/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH

WORKDIR /app

# Cache directory for dispersion results (mounted volume on Railway)
RUN mkdir -p /app/.cache

ENV PYTHONUNBUFFERED=1 \
    DISPERSION_CACHE_DIR=/app/.cache \
    PORT=8765

EXPOSE 8765

# Healthcheck for Railway's liveness probes
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Single uvicorn worker — our requests are CPU-bound and short.
# Bump to 2 workers if Railway plan provides 1+ vCPU.
CMD ["sh", "-c", "uvicorn tijuana_dispersion.api:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]
