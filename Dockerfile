# syntax=docker/dockerfile:1.7
# Build: docker build --progress=plain .
# The runtime stage intentionally ships only /app/.venv + source; toolchain
# (uv, pip, build caches) stays in the builder layer.
ARG PYTHON_VERSION=3.12-slim-bookworm

FROM python:${PYTHON_VERSION} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Same absolute path as the runtime stage: uv console-script entry points bake
# the interpreter's absolute path into .venv/bin/* shebangs, so a venv built at
# /build and copied to /app breaks with "alembic: not found" (exit 127).
WORKDIR /app
# Pinning uv keeps the dependency resolver byte-for-byte reproducible.
RUN pip install uv==0.12.5
COPY pyproject.toml uv.lock README.md ./
# --mount=type=cache lets rebuilds reuse downloaded wheels; --locked enforces
# the uv.lock hash and --no-dev/--no-install-project keeps the runtime venv lean.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

FROM python:${PYTHON_VERSION} AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Static, non-root, no login shell; keep UID stable so mounted volumes can be
# chowned once by the operator.
RUN groupadd --system --gid 10001 office \
    && useradd --system --uid 10001 --gid office --home-dir /home/office --shell /usr/sbin/nologin office \
    && mkdir -p /app/uploads && chown office:office /app/uploads
COPY --from=builder --chown=office:office /app/.venv /app/.venv
COPY --chown=office:office alembic.ini ./
COPY --chown=office:office migrations ./migrations
COPY --chown=office:office app ./app
USER office
EXPOSE 8000
# The slim image has no curl/wget; use the interpreter already on PATH and
# the /ready endpoint the app exposes for liveness.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).status == 200 else 1)"]
# OCI image annotations for supply-chain provenance.
LABEL org.opencontainers.image.title="ai-office-api" \
      org.opencontainers.image.source="https://github.com/citron99/ai_office" \
      org.opencontainers.image.base.name="docker.io/library/python:${PYTHON_VERSION}"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
