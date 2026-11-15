# ── Stage 1: Build the Vue frontend ──────────────────────────────────
FROM mirror.gcr.io/library/node:24-alpine AS frontend-builder

# Same layout as the repo (src/js builds into ../py/web/static) so vite's outDir resolves unchanged
WORKDIR /build/src/js
COPY src/js/package.json src/js/package-lock.json* ./
RUN npm install
COPY src/js/ ./
RUN npm run build

# ── Stage 2: Python API runtime ─────────────────────────────────────
FROM mirror.gcr.io/library/python:3.13-slim

# System deps for opencv (cv2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code in the repo's own layout (the code finds the repo root
# three levels above web/api.py): the whole src/py tree so every subpackage —
# core, providers, chat — is included; static is .dockerignored and re-copied
# from the frontend build below
COPY src/py/ ./src/py/
COPY alembic/ ./alembic/
COPY alembic.ini entrypoint.sh ./

# Copy built frontend into web/static (where vite outputs it)
COPY --from=frontend-builder /build/src/py/web/static ./src/py/web/static/


# Data directory (db + assets + cache) will be mounted as a volume
ENV CYNO_DATA_DIR=/data
# The `web` package lives in src/py
ENV PYTHONPATH=/app/src/py
# App logs go to stdout, which Python block-buffers when it isn't a terminal:
# without this they sit in the buffer and never reach `docker logs`.
ENV PYTHONUNBUFFERED=1

RUN groupadd -r cyno && useradd -r -g cyno cyno && \
    chmod +x entrypoint.sh && \
    chown -R cyno:cyno /app
USER cyno

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
