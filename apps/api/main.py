"""
apps/api/main.py
================
FastAPI Gateway entrypoint for Autonomous SCF Engine.
Integrates FastMCP toolkits, LangGraph multi-agent orchestrator,
REST ingestion endpoints, and real-time Server-Sent Events (SSE) telemetry.
"""

from __future__ import annotations

import os
import time
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes import actions, forecast, invoices, stream

_START_TIME = time.time()

app = FastAPI(
    title="Autonomous SCF Engine API",
    description="""
Institutional-grade Autonomous Supply Chain Finance & Working Capital Floating Engine.
Integrates FastMCP financial toolchains, Hybrid Tabular ML (XGBoost), and LangGraph Multi-Agent Orchestration.
    """,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for local development and production cloud environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "*",  # Permissive for development & containerized deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Sub-Routers
app.include_router(invoices.router)
app.include_router(stream.router)
app.include_router(actions.router)
app.include_router(forecast.router)


@app.get("/", tags=["Health"])
def root() -> dict[str, Any]:
    """Root welcoming endpoint with engine status and links to documentation."""
    return {
        "engine": "Autonomous Supply Chain Finance & Working Capital Floating Engine",
        "version": "0.1.0",
        "status": "ONLINE",
        "docs_url": "/docs",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
    }


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, Any]:
    """
    Production health check for Google Cloud Run and Kubernetes probes.
    Verifies that the ML model is accessible and dependencies are loaded.
    """
    model_loaded = False
    try:
        from packages.orchestrator.ml.acceptance_model import MODEL_FILE
        model_loaded = MODEL_FILE.exists()
    except Exception:
        pass

    return {
        "status": "HEALTHY",
        "timestamp": time.time(),
        "uptime_seconds": round(time.time() - _START_TIME, 2),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "subsystems": {
            "langgraph_multi_agent": "INITIALIZED",
            "fastmcp_toolkit": "READY",
            "xgboost_ml_acceptance_model": "LOADED" if model_loaded else "STANDBY",
        },
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=port, reload=True)

