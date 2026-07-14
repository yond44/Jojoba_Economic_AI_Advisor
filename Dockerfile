FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_DIR=/app/fastembed_cache \
    GIT_PYTHON_REFRESH=quite

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt .

COPY src/ ./src/
COPY data/raw/ ./data/raw/
COPY n8n/ ./n8n/  

RUN pip install --timeout=600 --no-cache-dir -v -r requirements.txt

# Copy the rest of the source. Your compose file bind-mounts ./src and ./app
# over this at runtime for live-reload during development, but the image
# still needs *something* baked in so it can also run standalone (e.g. in
# a deploy where those volumes aren't mounted).
COPY . .

EXPOSE 8000

# This was the actual cause of "Exited (0) after 0 seconds": with no CMD,
# the base image's default `python3` REPL ran instead, hit EOF on stdin
# immediately (no TTY attached under docker-compose), and exited 0 right
# away — no error, nothing in the logs, just silence.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]