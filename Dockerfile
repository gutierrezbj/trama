# TRAMA en un solo contenedor: interfaz compilada + API + worker (FFmpeg estático).
FROM node:22-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TRAMA_DATA_DIR=/data TRAMA_HOST=0.0.0.0 TRAMA_PORT=8765
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
 && python -c "from static_ffmpeg import run; run.get_or_fetch_platform_executables_else_raise()" \
 && useradd --system --uid 1000 --home /data trama && mkdir -p /data && chown trama /data
COPY backend/trama backend/trama
COPY --from=web /src/frontend/dist frontend/dist
USER trama
WORKDIR /app/backend
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/auth/status', timeout=4)"
CMD ["python", "-m", "trama", "serve"]
