FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY --from=frontend /build/frontend/dist ./app/static
COPY database/init /app/database/init
COPY policies /app/policies
RUN useradd --create-home --uid 10001 complaintops && chown -R complaintops:complaintops /app
USER complaintops
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT', '8000')}/health/ready\", timeout=3)" || exit 1
CMD ["sh", "-c", "python -m app.services.db_init && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
