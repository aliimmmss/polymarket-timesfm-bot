# Polymarket Trading Bot
# Production Docker image

FROM python:3.11-slim as base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY docs/ ./docs/

# Create data directories
RUN mkdir -p data/logs data/paper_trades data/db

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Production stage
FROM python:3.11-slim as production

WORKDIR /app

# Copy from base stage
COPY --from=base /app /app
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

# Add non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import src; print('OK')" || exit 1

# Expose port for monitoring
EXPOSE 8080

# Default command - paper trading
CMD ["python", "scripts/btc_15m_monitor_v2.py", "--monitor", "--interval", "300"]

# Development stage
FROM base as development

# Install dev dependencies
RUN pip install pytest pytest-asyncio black isort flake8 mypy

# Copy tests
COPY tests/ ./tests/

# Development command
CMD ["/bin/bash"]
