FROM python:3.11-slim

# Set version
ENV VERSION=0.0.38

# Set working directory
WORKDIR /app

# Install system dependencies (including build tools for psutil)
RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    wget \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 visualmapper && \
    useradd -u 1000 -g visualmapper -m visualmapper

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py ./
COPY routes ./routes
COPY services ./services
COPY utils ./utils
COPY ss_modules ./ss_modules
COPY www ./www

# Create data directory
RUN mkdir -p /app/data && chown -R visualmapper:visualmapper /app

# Environment variables
ENV MQTT_BROKER=localhost
ENV MQTT_PORT=1883

# Switch to non-root user
USER visualmapper

# Expose ports
EXPOSE 8080 8099 8100

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8080/ || exit 1

# Start services
CMD ["python", "server.py"]
