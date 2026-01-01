FROM python:3.11-alpine

# Set version
ENV VERSION=0.0.10

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apk add --no-cache \
    nginx \
    supervisor \
    android-tools \
    && rm -rf /var/cache/apk/*

# Create non-root user
RUN addgroup -g 1000 visualmapper && \
    adduser -D -u 1000 -G visualmapper visualmapper

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Copy application files
COPY server.py adb_bridge.py ./
COPY www ./www

# Set ownership to non-root user
RUN chown -R visualmapper:visualmapper /app /var/log/nginx /var/lib/nginx /run/nginx

# Switch to non-root user
USER visualmapper

# Expose ports
EXPOSE 3000 8099 8100

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

# Start services
CMD ["python", "server.py"]
