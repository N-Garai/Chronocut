FROM python:3.11-slim

LABEL maintainer="chronocut"
LABEL description="ChronoCut API - Autonomous Documentary Orchestrator"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set workdir
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8000
# Rich overlays stay on the always-available engine for the free tier; the
# 512 MB instance cannot pass the 1 GB overlay-engine RAM gate.
ENV TEXT_OVERLAY_ENGINE=drawtext

EXPOSE 8000

CMD ["python", "-m", "app.main"]
