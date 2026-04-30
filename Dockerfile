# Dockerfile
# MeetMind — Privacy-first AI Meeting Intelligence
#
# Build:  docker build -t meetmind .
# Run:    docker-compose up

FROM python:3.12-slim

# System dependencies
# ffmpeg     — audio format conversion (m4a, mp3 → wav)
# git        — required by some pip packages at install time
# build-essential — needed to compile some Python extensions
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first — Docker layer cache means this only
# re-runs when requirements.txt changes, not on every code change
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories that need to exist at runtime
RUN mkdir -p audio

# Expose FastAPI port
EXPOSE 8000

# Health check — Docker will restart the container if this fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Start the server
# Workers=1 because the pipeline uses shared in-memory state (_sessions dict)
# and local model loading — multiple workers would conflict
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]