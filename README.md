# TRAMA
Tu biblioteca de producción. Un producto de JRGB.

TRAMA convierte un repositorio de recursos audiovisuales en una biblioteca visual: descubrir, entender, seleccionar y obtener el original.

## Estado
E1 (piloto local) implementado y verificado en el equipo del propietario el 2026-09-20: ver [BUILD_NOTES.md](BUILD_NOTES.md).
Destino previsto: https://trama.jrgblanco.com (no desplegado ni configurado; E3).
Drive, acceso online e integración con Escenda no están implementados.

## Arranque rápido (Windows)
Requisitos: Python 3.13 y Node 22 en el PATH. FFmpeg no es necesario: se descarga un binario estático dentro del entorno virtual.

```bat
scripts\setup.cmd
```
Edita `.env` (creado a partir de `.env.example`) y pon en `TRAMA_ALLOWED_ROOTS` las carpetas locales que TRAMA puede explorar, separadas por `;`.

```bat
scripts\serve.cmd
```
Abre http://127.0.0.1:8765. El catálogo y los derivados se guardan en `%LOCALAPPDATA%\TRAMA` (fuera de OneDrive).

Comandos individuales: `python -m trama check` (entorno), `python -m trama migrate`, `python -m trama serve`, todos desde `backend/` con el venv activo. Desarrollo de la interfaz: `npm run dev` en `frontend/` (proxy a la API en 8765).

Pruebas: `backend\.venv\Scripts\python -m pytest` desde `backend/`.

## Comienza aquí
1. [Encargo para el agente](docs/ENCARGO-AGENTE.md)
2. [Producto y experiencia](docs/PRODUCTO.md)
3. [Arquitectura propuesta](docs/ARQUITECTURA.md) y [ADR-001](docs/ADR-001-stack-e1.md)
4. [Identidad e interfaz](docs/IDENTIDAD.md)
5. [Plan de trabajo](tasks/todo.md)

## Alcance
V1: producción de vídeo, incluidos efectos sonoros y música para montaje.
V2: biblioteca DJ, pendiente de definición. Marketplace fuera del alcance actual.
TRAMA es independiente de Escenda. Su futura integración consumirá una API.

## Datos
Este repositorio es público. No almacenar aquí packs comprados, inventarios personales, rutas de usuario, credenciales, catálogos privados ni originales.
Los bocetos de interfaz son ilustrativos. El catálogo y el repositorio audiovisual deben ser privados.
Las capturas de `docs/capturas/` muestran únicamente las tres muestras autorizadas del encargo.
