# syntax=docker/dockerfile:1
# Sunroom: one image, one process (docs/PLAN.md §14.5). Build it with `just image`, which feeds
# `git archive` of a release tag as the context; never the working tree.

ARG NODE_IMAGE=node:26-slim@sha256:930557a230abacbc3f4fd9b8648abf8f4bee1e17cb72195dcdfb2f709bc85b33
ARG PYTHON_IMAGE=python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21

# ---- frontend: built once, natively, because its output is the same on every platform ----
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN npm install --global "pnpm@$(node -p "require('./package.json').packageManager.split('@')[1]")" \
 && pnpm install --frozen-lockfile
COPY VERSION /src/VERSION
COPY frontend/ ./
RUN pnpm exec vite build

FROM ${UV_IMAGE} AS uv

# ---- backend dependencies, installed for the target platform (wheels only) ----
FROM ${PYTHON_IMAGE} AS py
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime: non-root, read-only app files, all state on /data ----
FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION
ARG REVISION=unknown
ARG CREATED=unknown
LABEL org.opencontainers.image.title="Sunroom" \
      org.opencontainers.image.description="A family wall calendar for a shared screen at home and everyone's devices." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.source="https://github.com/ScopeXL/sunroom" \
      org.opencontainers.image.url="https://hub.docker.com/r/scopexl/sunroom" \
      org.opencontainers.image.licenses="MIT"
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sunroom \
 && install -d -o 10001 -g 10001 -m 0750 /data
COPY --from=py /app/.venv /app/.venv
COPY --from=web /src/frontend/dist /app/static
COPY VERSION /app/VERSION
RUN test -n "$VERSION" && test "$VERSION" = "$(cat /app/VERSION)" \
 && printf '{"version":"%s","revision":"%s","created":"%s"}\n' "$VERSION" "$REVISION" "$CREATED" \
    > /app/build-info.json
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    DATA_DIR=/data \
    PORT=8080 \
    SUNROOM_STATIC_DIR=/app/static \
    SUNROOM_CONTAINER=1 \
    SUNROOM_BUILD_INFO=/app/build-info.json
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --start-interval=2s --retries=3 \
  CMD ["python", "-m", "sunroom.healthcheck"]
ENTRYPOINT ["sunroom"]
CMD ["serve"]
