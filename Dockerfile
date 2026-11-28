# ── Stage 1: Build the Vue frontend ──────────────────────────────────
FROM mirror.gcr.io/library/node:26-alpine AS frontend-builder

# Same layout as the repo, so the build lands where the API looks for it (src/js/dist)
WORKDIR /build/src/js
COPY src/js/package.json src/js/package-lock.json ./
RUN npm ci
COPY src/js/ ./
RUN npm run build

# ── Stage 2: Python API runtime ─────────────────────────────────────
FROM mirror.gcr.io/library/python:3.15-slim

# Links the GHCR package to this repo (so it inherits the repo's visibility and access)
LABEL org.opencontainers.image.source="https://github.com/ptinkler/cyno-studio"

# Security updates for the base image's own packages (opencv-python-headless needs no system libraries).
# UPGRADE_STAMP changes on every CI run so the build cache never reuses an old upgrade layer.
ARG UPGRADE_STAMP=
RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml uv.lock ./
# uv installs exactly what uv.lock says (system site-packages); pip is dropped afterwards because
# its vendored msgpack/setuptools get flagged by scanners
ENV UV_PROJECT_ENVIRONMENT=/usr/local UV_NO_CACHE=1
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev && \
    pip uninstall -y pip uv

# Copy application code in the repo's own layout (the code finds the repo root
# three levels above web/api.py): the whole src/py tree so every subpackage —
# core, providers, chat — is included; the frontend build is added below
COPY src/py/ ./src/py/
COPY alembic/ ./alembic/
COPY alembic.ini entrypoint.sh ./

# Copy the built frontend to where the API serves it from
COPY --from=frontend-builder /build/src/js/dist ./src/js/dist/


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
