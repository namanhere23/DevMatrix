# Containerfile — NexusSentry
# Python application image

FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (cache layer)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Expose dashboard port
EXPOSE 7777

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "from nexussentry.agents.scout import ScoutAgent; print('OK')" || exit 1

# Default: run the demo
CMD ["python", "demo/run_demo.py", "--auto", "--skip-health"]
