# BUILD_NOTES — E1 piloto local

Fecha: 2026-09-20. Equipo: Windows 11 Home (garage1), 16 hilos, 145 GB libres en C:.
Agente: Claude (Fable 5.1) siguiendo `AGENTS.md` y `docs/ENCARGO-AGENTE.md`.

## Qué funciona (verificado con bytes reales)
- Incorporar una carpeta local (selector de raíz + subcarpetas servido por el backend), analizar con ffprobe, generar miniaturas, proxies y previews de alfa, explorar, filtrar, buscar, editar ficha, favoritos, colecciones, selecciones con orden y notas, y descargar el original.
- Reiniciar el servidor conserva catálogo, ediciones, derivados, favoritos, colecciones y selecciones (prueba automática y reinicio manual).
- Reimportar no duplica fichas; un archivo copiado con otro nombre se reconoce por SHA-256 y se une como segunda ubicación.
- Fuente desconectada: la ficha y las previews siguen disponibles; el original devuelve 404 explícito y la interfaz lo señala.
- Error de análisis visible en tarjeta, ficha e «Incorporar» (lista de trabajos con reintento y cancelación).

## Entorno inspeccionado
| Elemento | Resultado |
|---|---|
| Node / npm | v22.15.0 / 10.9.2 |
| Python / pip | 3.13.7 / 25.2 |
| FFmpeg en PATH | No. Se usa `static-ffmpeg` 3.0 → FFmpeg 8.0.1 essentials (gyan.dev), descargado en el venv la primera vez (`python -m trama check`). |
| Muestras | `Escritorio\Muestras-Audiovisual-58b96191` (3 archivos, 85 MB). |
| Pack | `Descargas\Pack Edicion`: 72 ZIP, 140 GB. Solo se listó su índice (sin extraer) para elegir una colección pequeña. |
| Colección elegida | `MEGA PACK EDICIÓN/NEON FX/PARTICULAS` y `.../REDES SOCIAIS`: 26 archivos (13 pares MOV ProRes 4444 + MP4), 1,18 GB, extraídos con validación de rutas a `Vídeos\TRAMA-muestras` (fuera del repo y de OneDrive). |

## Comandos ejecutados (reproducibles)
```bat
git clone https://github.com/gutierrezbj/trama.git
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend && npm install && npm run build && cd ..
copy .env.example .env   (editar TRAMA_ALLOWED_ROOTS)
backend\.venv\Scripts\python -m trama check
backend\.venv\Scripts\python -m trama migrate
scripts\serve.cmd        (equivale a: python -m trama serve)
backend\.venv\Scripts\python -m pytest    (desde backend\)
```
Resultado de `pytest`: 7 pruebas, 7 pasan (8,3 s). Cubren análisis y derivados reales sobre archivos sintéticos generados con FFmpeg (marcados como sintéticos), reimportación idempotente con ediciones conservadas, persistencia tras reinicio, fuente offline, descarga exacta con rangos, rutas que no escapan de las raíces permitidas, reintento/cancelación y cancelación de una importación a medias.

## Datos medidos de las muestras (ffprobe 8.0.1)
| Archivo | Medido |
|---|---|
| `Colorized 04.mov` (humo) | ProRes 4444, `yuva444p12le`, 1920×1080, 60 fps, 198 fotogramas, **3,300 s**, alfa presente y **usado** (píxeles no opacos medidos). |
| `FILMFILM_Film Strip Burns Transition 5.mov` | MJPEG `yuvj422p` 1920×1080 con matriz de rotación **90°** → se cataloga y reproduce como **1080×1920 vertical**, 25 fps, 1,160 s, con audio PCM 16 bit 44,1 kHz. |
| `Bubbles - Whoosh FX.wav` | PCM 24 bit, 48 kHz, estéreo, **8,584 s**. Reproduce en el navegador vía proxy AAC + forma de onda. |
| NEON FX (MOV) | ProRes 4444 `yuva444p12le`, alfa usado, 0,9–3,97 s, 30 fps. Los MP4 hermanos son `yuv420p` sin alfa (se muestran como «No»). |

Comprobaciones pedidas por el plan: rotación de la transición ✔, duración del humo ✔ (3,30 s, no 3:30 min), conservación de alfa ✔ (tres proxies sobre fondo oscuro/claro/cuadriculado; el navegador reproduce `preview?bg=checker` a 960×540), reproducción WAV ✔, reintentos ✔, persistencia ✔.

## Rendimiento medido (este equipo, 2 hilos de worker)
Incorporación de 29 archivos (1,27 GB) incluyendo hash SHA-256 completo, análisis y todos los derivados: **≈32 s** de extremo a extremo.

| Derivado | n | media | máx |
|---|---|---|---|
| thumb (JPEG ≤640 px) | 28 | 0,22 s | 0,49 s |
| proxy H.264 ≤960 px | 14 | 0,47 s | 0,87 s |
| proxy_dark / light / checker (alfa) | 14 c/u | 0,84–0,99 s | 1,54 s |
| waveform PNG | 1 | 0,08 s | — |
| audio_proxy AAC | 1 | 0,39 s | — |

Derivados en disco: 3,8 MB para 29 recursos. Búsqueda y listados: respuesta inmediata con 29 fichas (no se ha medido con miles; ver E2).

## Limitaciones y decisiones honestas
- La **categoría** se infiere de nombres de carpeta/archivo con reglas simples y se marca «inferida». Ejemplo real: `Colorized 04.mov` se clasificó como «Color» por su nombre; se corrigió a VFX a mano (queda registrado como humano). La regla se ajustó para no tratar «colorized» como LUT.
- No hay descripciones inferidas ni búsqueda semántica (sin IA en E1). Las descripciones son humanas o vacías, y se dice cuál es cuál.
- Los archivos `other` (LUT, plantillas, PDF…) se catalogan y descargan pero no tienen preview; la ficha lo indica.
- El estado «offline» de una ubicación se detecta al importar, al analizar y al pedir el original; no hay vigilancia continua del disco.
- Galería paginada (60 por página), no virtualizada. Suficiente para E1; E2 debe cambiarlo.
- Las previews de alfa son MP4 aplanados sobre fondos fijos, como pide `docs/PRODUCTO.md`. No se afirma que un archivo sea loop ni se recomiendan modos de fusión.
- El hover reproduce el proxy sobre cuadriculado, silenciado y uno a la vez; con `prefers-reduced-motion` no hay hover ni bucle.
- Marca: cabecera con rectángulo amarillo (CSS, no un archivo de marca) y hueco para el símbolo definitivo; no se ha redibujado el pez JRGB.
- Puerto y host fijos en loopback; sin autenticación (no se expone fuera del equipo).
- Advertencia de FastAPI sobre `on_event` (deprecación): funcional; migrar a `lifespan` cuando se toque la API.

## Verificación visual
Capturas en `docs/capturas/` (solo las tres muestras autorizadas, sin rutas de usuario):
1. `01-explorar-muestras-humo-alfa.png`: galería + ficha del humo con fondo cuadriculado, datos medidos y etiquetas.
2. `02-transicion-vertical.png`: la transición rotada se muestra vertical.
3. `03-audio-wav.png`: WAV con forma de onda y transporte.
4. `04-incorporar.png`: fuentes, carpeta, lotes y trabajos.

Ancho de teléfono (375 px) verificado en el navegador: la ficha pasa a panel superpuesto con botón de cierre y la navegación se pliega tras un botón de menú; no hay desbordamiento horizontal.
Comparación con `assets/reference/ui-*.jpg`: misma estructura (sidebar compacta, buscador superior, chips, galería, ficha lateral amplia con fondos de preview y acciones), misma paleta y radios. Diferencias deliberadas: sin campana ni avatar decorativos; los rótulos proceden del análisis real.

## Recorrido completo documentado
1. Incorporar → elegir «Muestras-Audiovisual-58b96191» → «Incorporar» (3 archivos, 0 errores).
2. Explorar → chip «Con transparencia» deja solo los ProRes 4444; «Vertical» deja la transición.
3. Abrir «Humo multicolor» → fondo cuadriculado → reproducir (960×540, 3,3 s) → editar descripción y etiquetas `humo`, `multicolor`, `revelación` → buscar «HÚMO»/«revelacion» la encuentra.
4. «Añadir a selección» → crear «Spot otoño» → Mis selecciones muestra la pieza con nota y orden.
5. «Descargar original» → `Colorized 04.mov`, 81 483 668 bytes, `Content-Disposition: attachment`, rangos 206.
6. Reiniciar `serve.cmd` → todo lo anterior sigue.
