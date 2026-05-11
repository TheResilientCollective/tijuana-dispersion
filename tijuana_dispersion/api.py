"""
FastAPI HTTP service wrapping the dispersion engine.

Run with:  uvicorn tijuana_dispersion.api:app --host 0.0.0.0 --port 8765

For Claude integration, this would be either:
  (a) Reachable via a public URL → Claude calls via web_fetch with POST,
  (b) Wrapped as an MCP server so endpoints become first-class tools.

The endpoints below mirror the Pydantic schemas exactly, so the JSON
contract is identical whether called via REST, MCP, or direct Python.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .schemas import (
    SCHEMA_VERSION,
    ForwardRunRequest,
    ForwardRunResult,
    InversionRequest,
    InversionResult,
)
from .service import run_forward, run_inversion

app = FastAPI(
    title="Tijuana H2S Dispersion Service",
    version=SCHEMA_VERSION,
    description=(
        "Forward dispersion and emission inversion for the Tijuana "
        "River Valley H2S monitoring network. Backends: gaussian_plume, "
        "hysplit (planned)."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "schema_version": SCHEMA_VERSION}


@app.post("/forward", response_model=ForwardRunResult)
def forward(req: ForwardRunRequest) -> ForwardRunResult:
    try:
        return run_forward(req)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"forward run failed: {e}") from e


@app.post("/inversion", response_model=InversionResult)
def inversion(req: InversionRequest) -> InversionResult:
    try:
        return run_inversion(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"inversion failed: {e}") from e
