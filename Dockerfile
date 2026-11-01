# Path-A dev image: the full API (agents, pipeline, furnace tooling) with the
# complete runtime, but no frontend stage and rich-overlay engine left on
# drawtext. Hosting uses the lean backend/Dockerfile image instead; any host
# runtime executes renders, not this dev image.
FROM python:3.11-slim

LABEL maintainer="chronocut"
LABEL description="ChronoCut API - Autonomous Documentary Orchestrator"

# System dependencies: FFmpeg is the render furnace.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    fonts-dejavu-core \
    fonts-liberation \
    curl \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY backend/app/ ./app/

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000
# This image never serves a frontend and never ships a Node/browser stack;
# kinetic overlays stay on the drawtext engine everywhere it is used.
ENV TEXT_OVERLAY_ENGINE=drawtext

# Expose the API port
EXPOSE 8000

# Start uvicorn (API-only)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
