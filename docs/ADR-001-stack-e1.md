# ADR-001 — Stack y entorno de E1

Estado: aceptado (2026-09-20). Ámbito: piloto local E1. Revisar al abordar E2/E3.

## Contexto
La arquitectura propuesta en `docs/ARQUITECTURA.md` pedía validar stack, versiones y entorno
antes de implementar. El entorno real inspeccionado (Windows 11, equipo `garage1`):

| Componente | Encontrado | Decisión |
|---|---|---|
| Node | v22.15.0, npm 10.9.2 | Se usa para Vite/React. |
| Python | 3.13.7 (`python`/`py`), pip 25.2 | Se usa para API y worker. |
| FFmpeg/ffprobe | No en PATH. Solo un `ffmpeg.exe` de CapCut sin `ffprobe`. | Binarios estáticos vía paquete `static-ffmpeg` dentro del venv (FFmpeg 8.0.1 essentials, gyan.dev). Sustituibles con `TRAMA_FFMPEG`/`TRAMA_FFPROBE`. |
| Muestras | 3 archivos en `Escritorio\Muestras-Audiovisual-58b96191` (WAV 24 bit, MOV ProRes 4444 con alfa, MOV MJPEG con rotación 90°). Pack completo: 72 ZIP, 140 GB en `Descargas\Pack Edicion`. | Muestras + extracción selectiva de dos subcarpetas de NEON FX (26 archivos, 1,2 GB) a `Vídeos\TRAMA-muestras`, fuera del repositorio. |
| Código | Clonado dentro de OneDrive (`02.SR docs\SRS\Trama`). | El catálogo y los derivados viven en `%LOCALAPPDATA%\TRAMA`, nunca en la carpeta sincronizada. |

## Decisiones
1. **Interfaz**: React 18.3 + TypeScript 5.9 + Vite 5.4, sin librería de componentes ni router externo (estado propio + hash). CSS con tokens de `docs/IDENTIDAD.md`.
2. **API**: FastAPI 0.141 sobre Starlette 1.6 (soporta rangos HTTP en `FileResponse`, verificado) con uvicorn 0.53, ligada a `127.0.0.1:8765`. Sirve también la interfaz compilada.
3. **Worker**: hilos dentro del mismo proceso que la API (`TRAMA_WORKERS`, por defecto 2) sobre una cola persistente en SQLite. Un solo proceso dueño del catálogo. Reclamación atómica de trabajos, cancelación por señal + `kill` del subproceso, reintentos manuales, recuperación de trabajos `running` al reiniciar. Un proceso separado no aporta nada en E1 y complicaría el arranque.
4. **Base de datos**: SQLite (módulo estándar, WAL, `foreign_keys=ON`) con migraciones SQL numeradas en `backend/trama/migrations/` aplicadas al arrancar. Sin ORM: consultas explícitas; los metadatos medidos se guardan como JSON y se filtran con `json_extract`.
5. **Modelo** (subconjunto del propuesto): `sources`, `asset_versions` (SHA-256 completo), `assets` (título/descripción/etiquetas/categoría con procedencia), `locations` (varias por versión, estado available/offline), `derivatives` (receta versionada), `jobs`, `imports`, `collections`/`collection_assets`, `selections`/`selection_items`. `Pack`/`PackEntry` quedan para E2 (ZIP).
6. **Identidad de bytes**: hash SHA-256 completo antes de crear o unir fichas. Nombre+tamaño+mtime solo permiten saltar el hash de una ruta ya conocida y sin cambios.
7. **Alfa**: se detecta por `pix_fmt` (lista explícita) y se **mide** si se usa (algún píxel no opaco en hasta 6 fotogramas). Un MP4 aplanado no conserva alfa, así que las previews con transparencia son tres proxies H.264 compuestos sobre fondo oscuro `#141618`, claro `#F2F0E9` y cuadriculado; la miniatura va sobre cuadriculado.
8. **Rotación**: dimensiones y orientación se calculan tras la matriz de rotación; los proxies se generan con el autorrotado de FFmpeg (verificado con la transición, 1920×1080 → 1080×1920).
9. **Audio**: proxy AAC (m4a) + forma de onda PNG (`showwavespic`, acento `#E8BE46`). Nunca autoplay.
10. **Búsqueda E1**: texto normalizado (minúsculas, sin acentos) sobre título, nombre original, descripción, etiquetas y ruta relativa; cada término debe aparecer.
11. **Seguridad de archivos**: originales y derivados se resuelven siempre por ID. Solo se exploran e importan subrutas de `TRAMA_ALLOWED_ROOTS`, con `resolve()` y comprobación de pertenencia. Sin IA de pago ni servicios externos.
12. **Sin dependencias de UI o de tests adicionales**: pytest + httpx (TestClient). Las pruebas generan archivos sintéticos con FFmpeg (marcados como tales) y cubren persistencia, reimportación, archivos y seguridad.

## Consecuencias
- Arranque en un comando (`scripts\serve.cmd`), sin servicios externos ni instalación global de FFmpeg.
- El catálogo está fuera de OneDrive; hay que respaldarlo aparte (E3).
- Para el pack completo (E2) harán falta: lectura segura de ZIP, jobs cancelables de larga duración con límites de disco, galería virtualizada y `Pack`/`PackEntry`.
- Si se desea GPU o mayor concurrencia, basta con ajustar `TRAMA_WORKERS`; el diseño de cola ya lo soporta.
