# ML Training Server Dockerfile
# Supports CPU, GPU (CUDA), and NPU (DirectML) acceleration

FROM python:3.11-slim

# Set version via build argument
ARG APP_VERSION=latest
ENV VERSION=$APP_VERSION

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements for ML training
COPY requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

# Copy ML training server and related files
COPY ml_components/ml_training_server.py .
COPY ml_components/model_exporter.py .

# Copy services (needed for FeatureManager)
COPY services/ /app/services/

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Create data directory
RUN mkdir -p /app/data

# Environment variables (can be overridden in docker-compose)
ENV MQTT_BROKER=localhost
ENV MQTT_PORT=1883
ENV USE_NPU=false
ENV DATA_DIR=/app/data

# Health check - verify process is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pgrep -f "ml_training_server" || exit 1

# Run ML training server (shell form to expand env vars)
CMD python ml_training_server.py --broker $MQTT_BROKER --port $MQTT_PORT
