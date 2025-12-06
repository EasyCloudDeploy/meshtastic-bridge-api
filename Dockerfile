# Multi-stage build for Meshtastic Relay API
FROM python:3.11-slim as builder

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN chmod +x /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy VERSION file
COPY VERSION ./
# Read version from VERSION file (can be overridden with --build-arg)
ARG APP_VERSION
RUN if [ -z "$APP_VERSION" ]; then \
      APP_VERSION=$(cat VERSION | tr -d '[:space:]'); \
    fi && \
    echo "Building version: $APP_VERSION" && \
    echo "$APP_VERSION" > /app/.version

# Copy dependency files
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

# Install dependencies using UV
RUN uv pip install --system --no-cache -e .

# Production stage
FROM python:3.11-slim

# No additional runtime dependencies needed
# (gcc was only needed for building, not runtime)

# Set working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app/src/ ./src/

# Copy VERSION file for runtime access
COPY --from=builder /app/VERSION ./VERSION

# Set version as build arg (can be overridden with --build-arg APP_VERSION=x.y.z)
# If not provided, version.py will read from VERSION file at runtime
ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run the application
CMD ["uvicorn", "meshtastic_relay_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

