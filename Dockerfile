# Tijuana H2S Dispersion Service
# Slim multi-stage build, ~150 MB final image.
# Designed for Railway free/hobby tiers (512 MB RAM, 1 vCPU).

FROM python:3.12-slim AS builder

# Build deps for any wheels that need to compile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim

# Just runtime essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pull installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY tijuana_dispersion ./tijuana_dispersion

# Cache directory for dispersion results (mounted volume on Railway)
RUN mkdir -p /app/.cache

ENV PYTHONUNBUFFERED=1
ENV DISPERSION_CACHE_DIR=/app/.cache

# Railway sets $PORT; default to 8765 for local dev
ENV PORT=8765
EXPOSE 8765

# Healthcheck for Railway's liveness probes
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Single uvicorn worker — our requests are CPU-bound and short.
# Bump to 2 workers if Railway plan provides 1+ vCPU.
CMD uvicorn tijuana_dispersion.api:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers 1 \
    --log-level info
