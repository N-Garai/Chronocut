FROM python:3.11-slim

LABEL maintainer="chronocut"
LABEL description="ChronoCut API - Autonomous Documentary Orchestrator"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create swap file to prevent OOM on Render free tier (512MB RAM)
RUN fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024 \
    && chmod 600 /swapfile \
    && mkswap /swapfile \
    && swapon /swapfile \
    && echo '/swapfile none swap sw 0 0' >> /etc/fstab

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

EXPOSE 8000

CMD ["python", "-m", "app.main"]
