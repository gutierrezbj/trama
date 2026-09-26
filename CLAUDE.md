# TRAMA — Claude Code Project Context

## What is this
Biblioteca privada de recursos de producción audiovisual de JuanCho (JRGB): packs ZIP y carpetas
convertidos en una biblioteca visual para encontrar, previsualizar, guardar en un proyecto y obtener
el original. Herramienta interna (Cuaderno de Protocolos JRGB, Kickoff parcial). Notion: Apps /
Personales / «TRAMA — Biblioteca de producción».

## Current State
- Entregas E1, E2, E3 y E3b-E3d en `main` (detalle y medidas en `BUILD_NOTES.md`).
- Los 72 packs viven en el Google Drive del propietario (`TRAMA/Packs`, verificados por md5);
  TRAMA extrae desde Drive por rangos HTTP y genera vistas previas sin guardar copias.
- Corre en el PC del propietario (garage1). Despliegue en Servidor 1 preparado (offset +260,
  `trama.jrgblanco.com`), ver `docs/DESPLIEGUE.md`.
- Pendiente: E4 integración con Escenda.

## Tech Stack
Python 3.13 + FastAPI + uvicorn; SQLite (WAL) con migraciones numeradas; worker en hilos con cola
persistente; FFmpeg estático (paquete `static-ffmpeg`). React 18 + TypeScript + Vite. Google Drive
REST v3 con httpx (OAuth PKCE, alcance `drive.file`). Desviación del stack estándar en ADR-001.

## Project Structure
- `backend/trama/`: `api.py` (FastAPI), `worker.py` (cola y trabajos), `packs.py` (ZIP seguros,
  extracción, `PackReader`), `drive.py` (OAuth, subida reanudable, `RemoteFile`), `media.py`
  (análisis y derivados), `backup.py`, `auth.py`, `migrations/`.
- `backend/tests/`: pytest (persistencia, reimportación, archivos, seguridad, Drive simulado).
- `frontend/src/`: vistas Explorar, Proyectos (selecciones), Colecciones, Fuentes y packs, Drive y copias.
- `docs/`: producto, arquitectura, identidad, ADR, despliegue. `tasks/`: `todo.md`, `lessons.md`.

## Key Patterns
- Leer `AGENTS.md` antes de tocar nada: originales intocables, nada de medios/inventarios/rutas/
  credenciales en este repo público, sin desplegar ni tocar DNS sin encargo.
- Datos de ejecución fuera del repo: `%LOCALAPPDATA%\TRAMA` (Windows) o `/data` (contenedor).
- Todo lo largo es un trabajo de la cola (reanudable tras reinicio); nunca en la petición HTTP.
- Identidad por SHA-256 al tener los bytes; provisional (crc32+tamaño) antes. Duplicados solo por hash.
- Cada incremento se cierra en `BUILD_NOTES.md` con comandos, medidas y limitaciones.

## Deploy
Local (Windows): `scripts\setup.cmd` y `scripts\serve.cmd` → http://127.0.0.1:8765.
Pruebas: `backend\.venv\Scripts\python -m pytest` desde `backend/`.
Servidor 1: `docker compose up -d --build` en `/opt/apps/trama` (puerto 127.0.0.1:3260), nginx +
Certbot delante; pasos completos en `docs/DESPLIEGUE.md`.
