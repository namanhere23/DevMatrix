# Containerfile — NexusSentry
# Multi-stage build: Python + Rust for the full pipeline

FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Install Rust toolchain
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copy and install Python dependencies first (cache layer)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

# Build Claw Code (if cloned)
RUN if [ -d "claw-code/rust" ]; then \
        cd claw-code/rust && cargo build --release; \
    else \
        echo "Claw Code not found — running in demo mock mode"; \
    fi

# Expose dashboard port
EXPOSE 7777

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "from nexussentry.agents.scout import ScoutAgent; print('OK')" || exit 1

# Default: run the demo
CMD ["python", "demo/run_demo.py", "--auto", "--skip-health"]
