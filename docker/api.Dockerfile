# SPDX-License-Identifier: AGPL-3.0-or-later
# One image for the api and the worker (different commands). Build context: repo root.

FROM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
COPY examples/ /app/examples/
RUN uv sync --frozen --no-dev
COPY --from=frontend /src/frontend/dist /app/static
RUN useradd --system --uid 10001 opencredential
USER opencredential
ENV OC_STATIC_DIR=/app/static
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["oc", "api", "--host", "0.0.0.0", "--port", "8000"]
