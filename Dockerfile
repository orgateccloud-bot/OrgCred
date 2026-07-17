# OrgCred — imagem multi-stage: build do frontend (Vite) + backend (uv),
# servidos por um único processo FastAPI (Fase F4 — ver app/main.py,
# StaticFiles com fallback de SPA).
FROM node:24-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /bin/bash orgcred
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY --from=frontend-builder /frontend/dist ./static/

USER orgcred

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
