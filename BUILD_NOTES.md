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

---

# BUILD_NOTES — E2 pack completo

Fecha: 2026-09-21. Mismo equipo (garage1). Decisiones en `docs/ADR-002-packs-e2.md`.

## Qué funciona (verificado con el pack real)
- **Indexar ZIP sin extraer**: desde «Incorporar» se ven los ZIP de la carpeta y se indexan uno a uno o todos. Cada entrada queda catalogada con identidad provisional (crc32 + tamaño), categoría inferida de su carpeta interna y procedencia (pack + ruta interna). Nada se escribe fuera del catálogo.
- **ZIP seguros**: rutas absolutas, con unidad, con `..`, enlaces simbólicos, profundidad > 32, entradas > 16 GB, ratio de compresión sospechoso y ZIP anidados se rechazan y se listan en la ficha del pack. Al extraer se comprueba el tamaño real contra el declarado y que el destino quede dentro de la caché.
- **Extracción selectiva** por entrada, carpeta (árbol con recuentos y bytes) o pack completo, como trabajo cancelable con progreso por bytes. La descarga de un original archivado extrae solo esa entrada bajo demanda.
- **Límites de disco**: caché máxima (`TRAMA_CACHE_MAX_GB`, 30) y espacio libre mínimo (`TRAMA_MIN_FREE_GB`, 10). Al superarse, la API responde 507 antes de encolar y el worker detiene el lote con error legible conservando lo extraído. «Liberar» borra copias de la caché (nunca el ZIP), la ficha y las previews siguen.
- **Duplicados**: misma crc32+tamaño → una sola ficha candidata con varias ubicaciones; al extraer, el SHA-256 confirma o separa. Duplicado confirmado contra una ficha existente: la provisional sin ediciones se retira; con ediciones o pertenencias se conserva enlazada (`duplicate_of`). `/api/duplicates` y el filtro «Solo duplicados y candidatos» los muestran. No se borra ningún archivo.
- **Galería virtualizada**: 8482 fichas con ~27 tarjetas montadas a la vez, páginas de 120 pedidas según el desplazamiento, sin errores en consola.
- **Formatos sin preview**: plantillas/proyectos muestran la aplicación necesaria y, si existe, la preview del proveedor (archivo hermano). LUT `.cube/.3dl`: cabecera leída (título, tamaño de malla) y demostración antes/después sobre imagen sintética, rotulada como demostración.
- **Inventario privado** CSV por pack en `%LOCALAPPDATA%\TRAMA\inventarios` (fuera del repo).

## Comandos ejecutados
```bat
backend\.venv\Scripts\python -m trama migrate      (aplica 0002_packs.sql)
scripts\serve.cmd
cd frontend && npm run build
backend\.venv\Scripts\python -m pytest             (desde backend\)
```
Resultado de `pytest`: 14 pruebas, 14 pasan (15,9 s): las 7 de E1 más 7 de E2 (ZIP inseguro con 7 entradas rechazadas, identidad provisional, extracción selectiva y descarga bajo demanda, liberación de caché, persistencia tras reinicio, duplicado confirmado que se funde, duplicado con ediciones que se conserva enlazado, límite de caché que detiene el lote, ZIP ignorado al incorporar carpetas, preview del proveedor y demostración de LUT).

## Medidas sobre el pack real (72 ZIP, 141 GB en `Descargas\Pack Edicion`)
| Operación | Medido |
|---|---|
| Indexar los 72 ZIP (lectura del directorio central + catálogo) | **2,9 s** en total. 9213 entradas multimedia, 0 rechazadas, 8482 fichas (731 entradas comparten crc32+tamaño y se agrupan como candidatas). |
| Listar página 4000–4120 del catálogo | 0,27 s |
| Búsqueda textual «neon particulas» sobre 8482 fichas | 0,23 s (20 resultados) |
| Extraer + hash + análisis + proxies de 35 entradas (962 MB: 12 fondos de vídeo 1080p de 5–30 s, 24 vídeos de plantillas, 4 LUT) | 74,7 s → 12,9 MB/s **incluyendo** ffprobe y proxies H.264; la extracción sola es una fracción pequeña (no medida por separado). |
| Caché tras esa prueba | 970 MB extraídos; 89 MB de derivados. |
| Duplicados confirmados por hash tras extraer | 3 grupos (los mismos fondos repetidos en varios ZIP); 481 grupos candidatos sin confirmar. |

Categorías inferidas del pack (solo por nombre de carpeta, revisables): VFX 1540, audio 3806, animación 802, transiciones 791, imágenes 653, overlays 500, color 298, fondos 65, plantillas 24, documentación 3.

## Limitaciones y decisiones honestas
- La identidad provisional no garantiza que dos entradas con la misma crc32 y tamaño sean idénticas; la interfaz lo marca «prov.» y «candidato» hasta extraer.
- El pack real no contiene MOGRT/AEP con vídeo hermano; el enlace «preview del proveedor» está probado solo con fixtures. Sus 24 «plantillas» son MP4 clasificados así por el nombre de carpeta.
- La demostración de LUT usa `testsrc2` (barras sintéticas), no material del usuario; es una orientación, no una previsualización real.
- Extraer todo el pack no cabe en el disco actual (141 GB con ~140 GB libres) ni tendría sentido: el flujo previsto es extraer carpetas al trabajar y liberar la caché después.
- El estado de un ZIP que desaparece se detecta al indexar/extraer (`offline`), no de forma continua.
- No hay vista dedicada de duplicados: existe el filtro y el endpoint.

## Verificación visual
- `docs/capturas/05-packs-incorporar.png`: ZIP de una carpeta con botones de indexar, packs indexados con recuentos y uso de caché.
- `docs/capturas/06-pack-carpetas.png`: árbol de carpetas de un pack con extraer/liberar por carpeta.
- `docs/capturas/07-lut-demo.png`: ficha de un LUT con la demostración antes/después rotulada.
- `docs/capturas/08-galeria-archivados.png`: galería virtualizada con recursos catalogados sin extraer.
Ancho de teléfono: sin cambios respecto a E1 (ficha superpuesta, navegación plegable).

---

# BUILD_NOTES — E3 acceso privado, Google Drive y respaldos

Fecha: 2026-09-21. Mismo equipo (garage1). Decisiones en `docs/ADR-003-acceso-drive-e3.md`.

## Qué funciona (verificado)
- **Acceso privado** (`TRAMA_AUTH_MODE=password`): contraseña del propietario con PBKDF2-SHA256, cookie de sesión firmada (HttpOnly, SameSite=Strict, Secure opcional), bloqueo progresivo por IP tras 5 fallos persistido en SQLite, tokens portadores para integraciones. Toda la API, incluidas previews y originales, responde 401 sin sesión; la interfaz muestra la pantalla de acceso y cierra sesión desde la cabecera. `python -m trama set-password` genera el hash; `check` avisa si se escucha fuera de loopback sin contraseña.
- **Adaptador Google Drive** con alcance mínimo `drive.file`, OAuth con PKCE, carpeta privada «TRAMA», subida reanudable por trozos (sesión y offset persistidos en el trabajo; ante un 5xx consulta a Drive dónde se quedó y continúa) y **verificación md5** antes de registrar la ubicación remota; si no coincide, se borra el remoto y el trabajo falla. Descarga de un original que solo está en Drive en streaming con rangos a través de TRAMA (sin enlaces de Drive). Acciones: «Copiar a Drive» en la ficha, «Copiar la selección a Drive», «Comprobar en Drive», conectar/desconectar en «Copias y Drive».
- **Respaldos**: snapshot consistente (API de copia de SQLite + derivados + manifiesto con SHA-256), retención configurable, verificación, subida opcional a Drive, comandos `backup` / `verify-backup` / `restore` y creación desde la interfaz. Restauración ensayada en test: se borra estado vivo, se restaura y vuelven etiquetas, favoritos, selecciones y previews; lo anterior se conserva como `*.pre-restore-<fecha>`; un snapshot corrupto se rechaza antes de tocar nada.
- **Disponibilidad explícita**: `available` (copia local aquí) frente a `remote_available` (copia verificada en Drive). La ficha distingue «fuente offline» de «solo en Drive».

## Qué NO se ha hecho (por diseño o por falta de credenciales)
- **Drive no está conectado de verdad.** No existe un cliente OAuth (client_secret.json) en este equipo; el adaptador está probado únicamente contra un servidor simulado (`tests/test_e3.py::FakeDrive`) que implementa token, about, carpeta, subida reanudable con una interrupción a mitad, metadatos y descarga con rangos. La interfaz informa «No configurado» con las instrucciones. Ninguna medida de subida real.
- **No desplegado, sin dominio ni DNS** (AGENTS.md). Plan completo en `docs/DESPLIEGUE.md`.
- Catalogar carpetas ya existentes en Drive queda fuera (necesitaría `drive.readonly`).

## Comandos ejecutados
```bat
backend\.venv\Scripts\python -m trama migrate          (aplica 0003_drive_backups.sql)
backend\.venv\Scripts\python -m trama check            (muestra modo de acceso, Drive y respaldos)
backend\.venv\Scripts\python -m pytest                 (desde backend\)
cd frontend && npm run build
scripts\serve.cmd
```
Resultado de `pytest`: 20 pruebas, 20 pasan (24,3 s): las 14 de E1/E2 más 6 de E3 (toda la API bloqueada sin sesión incluidas previews y originales, cookie manipulada rechazada, token portador, bloqueo tras 5 fallos, modo contraseña mal configurado avisado, respaldo → destrucción → restauración → verificación → corrupción detectada → retención, Drive: OAuth con state falso rechazado, subida por trozos con interrupción simulada y reanudación, bytes y md5 exactos, original servido en streaming desde Drive con rango 206, snapshot subido a Drive, desconexión, y Drive no configurado explícito).

## Medidas en este equipo
| Operación | Medido |
|---|---|
| Snapshot del catálogo real (8482 fichas: catálogo 19 MB + 176 derivados, 89 MB) desde la interfaz | **1,0 s**; `verify` correcto. El test crea, destruye y restaura un catálogo de 4 fichas en < 1 s. |
| API sin sesión sobre el servidor real | `/api/assets`, `/api/assets/{id}/thumb` → 401; `/` (interfaz) → 200; contraseña incorrecta → 401; correcta → cookie de sesión y 8482 fichas. |
| Coste del hash de contraseña | 310 000 iteraciones PBKDF2, ~0,2 s por intento (freno adicional a fuerza bruta). |

## Verificación visual
- `docs/capturas/09-acceso.png`: pantalla de acceso.
- `docs/capturas/10-copias-drive.png`: vista «Copias y Drive» con Drive no configurado y snapshots.

## Verificación con Google Drive real (2026-09-21)

Conectado con un cliente OAuth propio (tipo «App de escritorio», modo Prueba) a la cuenta real del propietario:

| Comprobación | Resultado real |
|---|---|
| OAuth con cuenta real | Conectado como `gutierrezbj@gmail.com`, carpeta privada «TRAMA» creada, alcance `drive.file`. |
| Subida real del humo (`Colorized 04.mov`) | **81.483.668 bytes en 8,0 s (≈9,7 MB/s)**, md5 `37fa8cb0b48f…` verificado contra Google. |
| Comprobar en Drive | Devuelve nombre, tamaño y md5 correctos del archivo en la cuenta. |
| Descarga desde Drive | Archivo completo (81 MB, md5 idéntico) y rango parcial (206). |

Corregido en pruebas reales: `drive-verify` elegía cualquier ubicación de Drive; ahora prioriza la disponible sobre una offline antigua (`test_drive_verify_prefers_available_location`). El cliente OAuth y el token viven solo en `%LOCALAPPDATA%\TRAMA\drive\`, fuera del repositorio. Modo Prueba: Google caduca el permiso a los ~7 días; TRAMA avisa y reconectar es un clic. Se publica la app (fin de la caducidad) cuando exista `trama.jrgblanco.com` con página y política, en el encargo de despliegue.
