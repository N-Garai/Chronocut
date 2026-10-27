# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app

# Copy frontend source and install dependencies
COPY frontend/ ./frontend/
WORKDIR /app/frontend
RUN npm install
RUN npm run build

# Stage 2: Production image
FROM python:3.11-slim

LABEL maintainer="chronocut"
LABEL description="ChronoCut API - Autonomous Documentary Orchestrator"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    gnupg \
    ca-certificates \
    # Chromium / chrome-headless-shell shared libraries for HyperFrames (N).
    # `unzip` is REQUIRED: `hyperframes browser ensure` downloads chrome-headless-shell
    # as a zip and extracts it; without unzip the download "succeeds" but extraction
    # fails ("no zip archiver is available") and the browser is never installed.
    unzip \
    # System Chromium: a reliable, apt-installed browser. We point HyperFrames at it
    # via PUPPETEER_EXECUTABLE_PATH so the flaky 'browser ensure' download is no longer
    # a hard requirement -- HyperFrames works even if that download fails.
    chromium \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 libxshmfence1 \
    fonts-liberation fonts-dejavu-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Create swap file to prevent OOM on Render free tier (512MB RAM)
RUN fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024 \
    && chmod 600 /swapfile \
    && mkswap /swapfile \
    && (swapon /swapfile || echo "Swap not enabled in container") \
    && echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Copy built frontend from builder stage
COPY --from=frontend-builder /app/frontend/dist /var/www/html

# Set workdir
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY backend/app/ ./app/

# --- HyperFrames (N) kinetic-typography overlay engine ---
# Install Node 22 (LTS) and the HyperFrames CLI globally, then download its
# chrome-headless-shell browser. Both Render and Cloud Run build from this single
# Dockerfile, so the Node + Chromium dependency is baked in at build time.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g hyperframes \
    # Bounded retry so a flaky/looping Chrome Headless Shell download can never hang
    # the build forever. Per-attempt timeout kills the @puppeteer/browsers retry loop;
    # on total failure the renderer falls back to MoviePy (text overlays still burn via
    # ffmpeg drawtext), so the API stays functional without the browser.
    && for i in 1 2 3 4 5; do timeout 600 hyperframes browser ensure && break \
       || echo "hyperframes browser ensure attempt $i failed, retrying"; done \
    || echo "chrome-headless-shell download failed; API falls back to MoviePy overlays"

# Wrap chrome-headless-shell so every launch injects the container-safe flags from
# HYPERFRAMES_CHROME_ARGS. Root containers (Render/Cloud Run) require --no-sandbox,
# and /dev/shm is too small for Chrome without --disable-dev-shm-usage. Reading the
# env at launch (not build time) lets the config drive the flags at runtime.
RUN REAL=$(find /root -type f -name chrome-headless-shell 2>/dev/null | head -n1) \
    && if [ -n "$REAL" ]; then \
        mv "$REAL" "${REAL}.bin" \
        && printf '#!/bin/sh\nexec "$(dirname "$0")/chrome-headless-shell.bin" ${HYPERFRAMES_CHROME_ARGS:---no-sandbox --disable-dev-shm-usage --single-process} "$@"\n' > "$REAL" \
        && chmod +x "$REAL"; \
    fi

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000

# HyperFrames (N): use the engine in deployment, point at the global CLI binary,
# and apply container-safe Chrome flags + low-memory mode for the 512MB free tier.
ENV TEXT_OVERLAY_ENGINE=hyperframes
ENV HYPERFRAMES_BIN=/usr/local/bin/hyperframes
ENV HYPERFRAMES_CHROME_ARGS="--no-sandbox --disable-dev-shm-usage --single-process"
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV PRODUCER_LOW_MEMORY_MODE=1

# Expose ports
EXPOSE 8000

# Start uvicorn serving API + frontend
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
