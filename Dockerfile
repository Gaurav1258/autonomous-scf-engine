# =============================================================================
# Autonomous Supply Chain Finance Engine — FastAPI & Orchestrator Gateway
# Multi-stage production container optimized for Google Cloud Run
# =============================================================================

FROM python:3.11-slim AS base

# Install uv from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set environment flags
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/workspace \
    PORT=8080

WORKDIR /workspace

# 1. Install system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Copy workspace configurations for layer caching
COPY pyproject.toml uv.lock* ./
COPY packages/mcp_server/pyproject.toml ./packages/mcp_server/
COPY packages/orchestrator/pyproject.toml ./packages/orchestrator/
COPY apps/api/pyproject.toml ./apps/api/

# 3. Pre-install dependencies into virtual environment
RUN uv sync --frozen --no-install-project --no-dev || uv sync --no-dev

# 4. Copy application source code
COPY packages/ ./packages/
COPY apps/ ./apps/
COPY pytest.ini ./

# 5. Final workspace installation
RUN uv sync --no-dev

# Cloud Run defaults to port 8080
EXPOSE 8080

# Run FastAPI gateway with uvicorn listening on dynamic Cloud Run $PORT
CMD ["sh", "-c", "uv run uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

