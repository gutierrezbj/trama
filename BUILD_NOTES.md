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

---

# BUILD_NOTES — E3b marca y biblioteca en la nube (2026-09-23)

## Qué se hizo
- **Marca**: el pez JRGB (recortado de `Arte/Logo_Trama.png`, que no se versiona) sustituye al rectángulo provisional en la cabecera, la pantalla de acceso y el favicon.
- **Packs a Google Drive**: los ZIP no son del propietario (venían de una carpeta compartida por otra persona), así que se copian tal cual a `TRAMA/Packs` en su Drive. Trabajo `pack_upload`: reanudable (sesión guardada; tras un corte pregunta a Drive el offset), verificado por md5 contra Google antes de registrar `packs.drive_file_id`. Uno a la vez. Migración `0004_packs_drive.sql`.
- **Extracción remota**: si el ZIP ya no está en local pero sí verificado en Drive, `extract_entry` abre el ZIP en Drive como archivo con `seek` (`drive.RemoteFile`) y pide por rangos HTTP solo el directorio central y la entrada pedida. La biblioteca sigue funcionando sin copia local de los ZIP.
- Decisión de destino: Google Drive (ya integrado y probado, 4,9 TB libres). OneDrive descartado porque su cliente tiende a sincronizar a disco local (disco al 87 %); iCloud sin API usable en Windows.

## Verificado
| Prueba | Resultado |
|---|---|
| Pack pequeño a Drive real | 8 KB, subido y verificado por md5 en 5 s, en `TRAMA/Packs`. |
| Subida masiva en curso | 71 packs, 139,9 GB encolados; ritmo observado ~5–6 MB/s ⇒ **6–8 h** estimadas. |
| Reanudación real | Servidor reiniciado con el ZIP 001 a 1.856/2.037 MB: al volver terminó desde ahí y quedó verificado. |
| Pruebas | 23/23 (nuevas: subida de pack reanudable y verificada; extracción de una entrada con el ZIP solo en Drive, y de una carpeta entera). |

## Pendiente (con OK explícito del propietario)
- Borrar los ZIP locales de `Descargas\Pack Edicion` **solo cuando los 72 estén verificados en Drive**. Irreversible; no se hace automáticamente.

## Cierre de la subida y prueba sin ZIP locales (2026-09-26)
- Subida terminada: **72/72 packs verificados por md5 en Drive** (150 GB, 0 fallos). Ritmo real ~8 MB/s: menos de 4 h.
- Prueba «solo nube»: la carpeta local de packs se aparta (renombrada, no borrada) para que TRAMA no la encuentre. Extracciones reales de packs elegidos al azar: todas con tamaño exacto, SHA-256 calculado y previsualizaciones generadas.
- **Corregido `RemoteFile`**: una lectura que empezaba dentro del búfer y acababa fuera descartaba el búfer y volvía a pedir los mismos bytes; además el bloque era fijo de 1 MB. Ahora sirve primero lo que ya tiene y, en lecturas secuenciales, el bloque se dobla hasta 32 MB (un salto vuelve a 1 MB).

| Entrada de ~152 MB desde Drive | Peticiones | Bytes bajados | Velocidad |
|---|---|---|---|
| Antes | 287 | 302 MB | 1,1 MB/s |
| Después | 9 | 167 MB | **21 MB/s** |

- Pruebas: 24/24 (nueva `test_remote_file_reads_sequential_entry_without_refetching`).
- Borrado de los ZIP locales: sigue pendiente del OK del propietario tras probar el uso real desde Drive.

---

# BUILD_NOTES — E3d vistas previas para todo y claridad (2026-09-26)

Motivo (prueba real del propietario): casi toda la biblioteca se veía como «En el pack, sin extraer», sin imagen; y «Incorporar», «Copias y Drive» y «Añadir a selección» no se entendían.

## Qué se hizo
- **Trabajo `preview_pack`**: por pack, abre el ZIP una sola vez (`packs.PackReader`, local o Drive por rangos), extrae lotes de 25 entradas, ejecuta en el propio hilo sus análisis y derivados (`_drain_media_jobs`, sin depender de otro hilo libre) y suelta siempre las copias extraídas. Quedan las vistas previas; los originales siguen en el ZIP. Reanudable: solo toma entradas cuya versión sigue con análisis pendiente. `GET/POST /api/packs/previews`.
- **Interfaz**: aviso «Vistas previas de tus packs — X de N» con el botón «Generar vistas previas» (Explorar y Fuentes y packs). Menú: «Proyectos» (antes «Mis selecciones»), sección «Ajustes» con «Fuentes y packs» (antes «Incorporar») y «Drive y copias». «Guardar en proyecto» en la ficha. «✕ Limpiar filtros» visible siempre que haya un filtro. Drive muestra packs y originales.

## Verificado
| Prueba | Resultado |
|---|---|
| Pack real de 2 GB solo en Drive, 39 recursos | 36 con vista previa en 2 min 50 s; 3 fallidos por archivos MP4 truncados dentro del propio pack («moov atom not found»), marcados como error de análisis. Ninguna copia extraída residual. |
| Estimación para toda la biblioteca | ~150 GB a ese ritmo ⇒ **unas 4 h**; derivados ~0,5 MB por recurso ⇒ ~4–5 GB locales (solo vistas previas). |
| Pruebas | 25/25 (nueva `test_previews_for_whole_pack_leave_no_extracted_copies`; la de Drive cubre también vistas previas con el ZIP solo en Drive). |

---

# BUILD_NOTES — E3e preparación del despliegue (2026-09-26)

Encargo del propietario: TRAMA como herramienta interna (Cuaderno de Protocolos JRGB, Kickoff parcial) en el Servidor 1, offset +260, `trama.jrgblanco.com` (registro A creado por el propietario y comprobado en 1.1.1.1, 8.8.8.8 y el DNS de Hostinger).

## Qué se hizo
- `Dockerfile` en dos etapas, `docker-compose.yml` (`trama-app` en `127.0.0.1:3260`), vhost nginx y `.env` de servidor de ejemplo en `deploy/`, `docs/DESPLIEGUE.md` al estándar JRGB.
- `CLAUDE.md`, `DESIGN.md`, `tasks/lessons.md`.
- `trama serve` se niega a escuchar fuera de loopback sin contraseña.

## Verificado en el Mac (bleu, Docker 29.6.2, arm64)
| Prueba | Resultado |
|---|---|
| Construcción de la imagen | OK. Primer intento: FFmpeg no disponible en ejecución (static-ffmpeg escribía un lock en site-packages con usuario sin privilegios) → corregido enlazando los binarios en `/usr/local/bin` al construir. |
| Pruebas dentro del contenedor | 25/25 con FFmpeg n8.0.1. |
| Arranque sin contraseña | Rechazado, como se esperaba. |
| Arranque como producción | Solo `127.0.0.1:3260`; `/api/assets` 401 sin sesión; contraseña errónea 401; correcta 200 y catálogo 200; interfaz servida; healthcheck `healthy`. |

Limitación: la imagen del servidor (x86_64) se construirá allí. Docker por SSH en el Mac necesita `DOCKER_CONFIG` temporal sin llavero y `DOCKER_HOST` al socket de Docker Desktop.

## Vistas previas completas y ficha (2026-09-27)
- Generación nocturna terminada: 71 packs en 4 h 39 min; 8.884 recursos con análisis y vistas previas, 33 archivos rotos de origen (26 MP4 truncados, 7 con datos inválidos). Derivados: 5,5 GB.
- Corregido tras la revisión del propietario: la ficha de una imagen aún dentro del pack decía «no hay preview todavía» y hablaba de identidad provisional. Ahora muestra la miniatura y el aviso distingue «el original sigue en su pack, la vista previa ya está» del caso provisional. El indicador superior pasa de «N sin extraer» a «N en packs».
- Revisión de los 33 errores de análisis: **22 eran basura de macOS** (AppleDouble `._nombre`, 4 KB, no multimedia), ahora ignorados al indexar y retirados del catálogo por la migración `0005_basura_macos.sql` (probada antes sobre una copia del catálogo real; copia de seguridad previa en `respaldos/`). De los 11 restantes, 10 transiciones de una misma carpeta tienen **todo su contenido a ceros** (descarga fallida en origen) y 1 MOV está cortado exactamente en 1 MiB, con una copia buena en otro pack.
- Ficha: botón de cerrar visible también en escritorio; «Reintentar» con el original dentro del pack vuelve a sacarlo del ZIP (antes respondía 409); el aviso ya no habla de identidad provisional cuando no lo es. Pruebas: 26/26 (nueva `test_macos_junk_in_zip_is_ignored`).

---

# BUILD_NOTES — Despliegue en el Servidor 1 (2026-09-27)

TRAMA en producción en **https://trama.jrgblanco.com** (Servidor 1, `/opt/apps/trama`, contenedor `trama-app` en `127.0.0.1:3260`, offset +260).

| Paso | Resultado |
|---|---|
| Imagen | Construida en el servidor (x86_64) con `docker compose build`. |
| Catálogo | Snapshot del PC (8.431 fichas, 17.969 archivos, 5,5 GB) enviado por `tar | ssh` en 15 min 44 s y restaurado con verificación de SHA-256. |
| Contraseña | Nueva del propietario; huella idéntica en el contenedor (comprobada por firma). |
| Drive | `client_secret.json` y `token.json` en el volumen (600, usuario `trama`); acceso a la carpeta TRAMA comprobado desde el servidor. |
| nginx + HTTPS | vhost desde `deploy/`; Certbot ejecutado por el propietario; Let's Encrypt hasta el 26 dic 2026; http → https 301; HSTS, X-Frame-Options, nosniff, Referrer-Policy. |
| Seguridad | Sin puertos Docker en 0.0.0.0; `/api/assets` 401 sin sesión; contenedor `healthy`. |
| Monitorización | `/opt/scripts/healthcheck.sh` → `TRAMA|trama-app|docker` (estado `up`); SA99 Mongo `vps-prod.projects.TRAMA` y `SEED_SERVERS` (también se añadió JRGB, que faltaba). Copias previas de los archivos tocados. |

Incidencias resueltas: compose interpretaba los `$` de la huella en `env_file` (se escapan como `$$`); el restore desde un montaje de solo lectura fallaba porque el catálogo está en WAL (se monta con escritura y `chown 1000`).
Pendiente: cliente OAuth «Aplicación web» para poder reconectar Drive desde el servidor (hoy se renueva con el token del cliente de escritorio); respaldo diario en cron.

---

# BUILD_NOTES — E4a Packs nuevos desde Drive (2026-09-27)

Motivo: el propietario compró un bundle con licencia comercial (entregado como descarga directa, «Download all» = un ZIP de ZIPs de 49 GB). Decisión: los packs viven en su Google Drive (5 TB) y TRAMA se alimenta desde allí; ni el PC ni el servidor guardan los ZIP.

- `python -m trama subir <zip…>` (en cualquier equipo con TRAMA y Drive conectado): saca cada ZIP interior de uno en uno a una carpeta temporal, lo sube reanudable a `TRAMA/Packs`, verifica md5 contra Google y borra la copia; salta los que ya están (mismo md5); PDF a `TRAMA/Documentos`.
- `POST /api/packs/drive-scan` y botón «Buscar packs nuevos en Drive» (Fuentes y packs): lista `TRAMA/Packs`, da de alta los ZIP que el catálogo no conoce (ni por id ni por md5), los indexa leyendo el directorio central por rangos y encadena sus vistas previas.
- `index_pack` indexa también packs que solo están en Drive.
- Servidor: carpeta de entrada `/entrada` (volumen) disponible como raíz permitida.
- Pruebas: 28/28 (nuevas: descubrimiento e indexado desde Drive con vistas previas y sin copia local; subida de un ZIP de ZIPs sin duplicados).

## Vistas previas del bundle 4K en el servidor (2026-09-27)
- 3 packs nuevos descubiertos en Drive e indexados por rangos en segundos (MASTER BUNDLE 2.237 recursos, TEXTURE 223, STICKERS 52). TEXTURE y STICKERS con vistas previas completas.
- MASTER BUNDLE se detuvo en el recurso 41: las tandas de 25 ProRes 4K superaban la caché de 5 GB del servidor, que además contaba ~2,9 GB de extracciones del PC que no existían en el servidor. Corregido: tandas limitadas al 40 % de la caché (`_preview_batches`) y reconciliación de la caché al arrancar (`reconcile_cache`). Pruebas: 30/30.

## Incidencia 28 sep 2026: TRAMA sin servicio tras ~11 h
- Síntoma: la página se cortaba («upstream prematurely closed», «Response content shorter than Content-Length») y la ficha y el resumen de trabajos daban 500, mientras Docker seguía marcando «healthy».
- Causa: el proceso tenía 1.023 de 1.024 descriptores abiertos. Cada hilo del servidor web abría su conexión SQLite (hilo-local) y `Database` guardaba una referencia fuerte en `_all`, así que las conexiones de hilos ya muertos nunca se cerraban.
- Arreglo: `Database` recoge y cierra las conexiones de hilos muertos al abrir una nueva; `/api/health` pública que abre la base de datos y un archivo (usada por el HEALTHCHECK de Docker y por healthcheck.sh); `ulimits.nofile` 65536 en compose. Servicio restablecido reiniciando el contenedor (las vistas previas se reanudaron solas).

## PDF como tutoriales (2026-09-28)
- Los PDF de los packs tienen vista previa (primera página, `pypdfium2`) y se extraen sus enlaces a vídeo (`pypdf`): reels de Instagram, YouTube, TikTok o Vimeo; se descartan perfiles, tiendas y promociones. La ficha muestra la página, «▶ Ver el efecto» y «Abrir PDF» (sacado del ZIP en Drive, sin descargar).
- Migración 0007: los PDF ya analizados sin soporte vuelven a la cola de vistas previas.
- Arreglado: en un proyecto, la descarga de un recurso que sigue dentro de su pack estaba bloqueada y marcaba «original offline» sin serlo.
- Caso real: los 56 tutoriales de Harry Allsop traen cada uno el enlace al reel del efecto (uno, además, a YouTube).

## Etiquetado nivel 1 (2026-09-28)
- Etiquetas automáticas sin IA ni coste (`trama/tags.py`), en `assets.auto_tags` (migración 0008), aparte de las humanas:
  - Etiquetas en el inglés estándar del oficio (el de DaVinci, Premiere y los packs), decisión del propietario; cada una guarda un alias en español que solo entra en la búsqueda («humo» encuentra lo etiquetado «smoke»).
  - De las carpetas y el nombre: ~70 etiquetas que reúnen sinónimos en inglés, español y portugués (smoke = humo/fumaça, whoosh = swish/swoosh…); las de sonido solo en audio; music o sfx según la carpeta más cercana; BPM y loop.
  - De lo medido: alpha (usado de verdad), 4k / full hd, vertical / horizontal / square, with audio, 50-60 fps, lut.
- Entran en la búsqueda, con su alias en español. Filtro `tag` (varias se combinan) y `/api/tags` con `kind` manual | carpeta | medida.
- Se recalculan al terminar un análisis, al indexar un pack y, entero, al arrancar si cambia `AUTOTAG_VERSION` (tabla `meta`).
- Interfaz: franja de etiquetas en Explorar (las más frecuentes y «Ver todas», con el formato medido aparte); en la ficha, las automáticas con trazo discontinuo y un toque filtra la biblioteca.
- Medida sobre el catálogo real del servidor (solo lectura): el 83 % de las fichas recibe al menos una etiqueta de contenido; el resto es casi todo música sin subgénero en la carpeta. Pruebas: 40/40.
- Pendiente (nivel 2): IA de visión para lo que las carpetas no dicen (colores, qué se ve), con coste visible.

## Títulos desde las carpetas (2026-09-28)
- Muchos packs nombran los archivos «2.mov», «F.mov», «_12.mp4» o «195.cube»; lo que dice qué son está en la carpeta. Cuando el nombre no tiene ninguna palabra de tres letras, el título se arma con las carpetas: «Color Transitions · 12», «CRT Fonts · Classic · F», «LUT 195». Se saltan carpetas genéricas (raíces de pack, UPPER CASE, PNG, 4K, V1…); una carpeta de una sola palabra toma el contexto de la de arriba.
- `assets.title_source` (migración 0009): file | folder | human. Lo puesto a mano nunca se recalcula. Se aplica en el mismo recalculo que las etiquetas (AUTOTAG_VERSION 3). En la ficha, el título armado lleva un aviso con el nombre real del archivo.
- Catálogo real (solo lectura): 2.447 de 10.896 títulos mejoran. Pruebas: 42/42.

## Nivel 2, paso A: color y luz sin IA (2026-09-28)
- `media.measure_look`: sobre la miniatura (96×96) mide el reparto de tonos entre los píxeles con color, la fracción con color, la luminosidad percibida y la fracción casi negra; se guarda en `analysis.look`.
- Etiquetas (kind `color`): red, orange, yellow, green, cyan, blue, purple, magenta (hasta dos, ≥25 % del color), black & white, dark, bright, black background (útil para modo pantalla). Con alfa no se juzga el fondo (la miniatura va sobre damero). Alias en español para buscar («naranja», «fondo negro»…).
- Se mide al generar la miniatura y, para las ya existentes, con el trabajo `look` que se encola al arrancar. AUTOTAG_VERSION 4.
- La franja de etiquetas cuenta dentro de lo que se ve (`/api/tags` acepta los mismos filtros que la galería): en VFX ya no salen music ni sfx. Fila «Color y luz» con muestras de color.
- Visto de paso: algunas miniaturas con alfa salen vacías (solo damero) porque el fotograma al 35 % cae antes del efecto (p. ej. un estallido de sangre). Pendiente: elegir el fotograma con más cobertura de alfa.
- Pruebas: 45/45.

## Nivel 2, paso B: prueba de IA de visión (2026-09-28)
- `trama/vision.py`: hoja de 3 fotogramas (20/50/80 %) sacada de la vista previa ya generada (nada se baja del pack); se envía con `detail: low` a modelos compatibles con la API de OpenAI: OpenAI (`TRAMA_OPENAI_API_KEY`) o un modelo local gratis (`TRAMA_LOCAL_VISION_URL`, LM Studio del Mac por Tailscale). Devuelve descripción en español y 3-8 etiquetas en inglés del oficio; las pistas de carpeta van en el prompt.
- Coste medido con los tokens reales de cada respuesta y la tabla `PRICES` (tarifa estándar de OpenAI a 28 sep 2026: gpt-6-luna 0,10/0,50 $ por millón; gpt-5.4-mini 0,75/4,50).
- Migración 0010: `ai_runs`, `ai_labels`, `ai_votes`. Trabajo `ai_test` reanudable (salta lo ya respondido); el fallo de un modelo no para la prueba.
- Página «IA de visión» (Ajustes): lanzar la prueba de 50 recursos repartidos por categorías, comparar lado a lado, votar el mejor, y ver coste y tiempo por modelo proyectados a toda la biblioteca.
- Sonda previa (Sun Burst): gpt-6-luna 1,9 s y ~0,00007 $; gpt-5.4-mini 1,3 s y ~0,0005 $; Qwen3-VL 8B en el Mac ~14 s la primera (carga) y 0 $.
- Pruebas: 47/47 (modelos simulados, sin red ni gasto).
- Primera prueba real (50 recursos): gpt-5.4-mini 50/50, 1,2 s, 0,030 $; Qwen3-VL 8B (Mac) 49/50, 4,4 s, 0 $; gpt-6-luna 36/50, 2,3 s, 0,005 $. Los 14 fallos de gpt-6-luna eran respuestas vacías: razonaba y agotaba el presupuesto de tokens. Arreglo: `reasoning_effort: none` en los modelos que lo admiten y 600 tokens de margen; el JSON se lee aunque venga texto detrás (fallo de Qwen). Botón «Reintentar las que fallaron» (solo lo fallido, se conserva lo respondido).

## Nivel 2, paso C: IA en toda la biblioteca (2026-09-29)
- Arreglo: a las imágenes fijas ya no se les dice «3 fotogramas» (los modelos inventaban movimiento); `sheet_what`: video3 | video1 | still.
- Trabajo `ai_full`: pasa toda la biblioteca visual por el modelo elegido, 4 peticiones a la vez, reintento ante 429/5xx, tope de gasto (se para solo) y reanudable (salta lo ya etiquetado por ese modelo).
- Migración 0011: `assets.ai_tags` y `assets.ai_model`. La descripción de la IA entra solo si no hay una escrita a mano (`description_source` inferred). Las etiquetas de la IA entran en la búsqueda, el filtro y la franja (kind `ia`); en la ficha van con ✦.
- Página «IA de visión»: panel «Toda la biblioteca» con modelo, tope y estimación medida en la prueba.
- Elección tras la prueba: gpt-6-luna (vocabulario más preciso, inventa menos, ~0,35-0,85 $ para 6.517 recursos). Pruebas: 50/50.

## Remate (2026-09-29)
- Limpieza de las etiquetas de la IA (`clean_ai_tags`, AUTOTAG_VERSION 5): fuera lo que TRAMA ya mide mejor (orientación, alfa, blanco y negro, fondo, 4K, loop) y los colores de detalle («blue text», «white line»); los plurales se unen al vocabulario («light leak» → «light leaks»); sin duplicar las etiquetas de carpeta. En la franja, las de la IA con menos de 3 usos no se listan (siguen en la ficha y la búsqueda).
- Vista previa para LUT (.cube/.3dl), PSD (imagen fusionada) y MOGRT (la imagen de muestra que trae dentro, también dentro del .aegraphic) de los packs: entran en «Generar vistas previas» (antes solo vídeo, audio, imagen y PDF). PSD y MOGRT también pasan por la IA de visión.
- «Limpiar filtros» con fondo de color.
- Incidencia: el acceso a Drive del servidor caducó (cliente OAuth en modo prueba: Google caduca el permiso a los 7 días). Solución definitiva: publicar la app (alcance `drive.file`, no sensible, sin verificación) y reconectar una vez.
- Pruebas: 51/51.

## Huella visual y «¡Epa, esto ya lo tenías!» (2026-09-29)
- Recuento de los 56 MOGRT: 106 piezas únicas; 25 vídeos de ejemplo; de 81 útiles, 76 ya estaban sueltas en el bundle. Las 5 nuevas (texturas) se subieron como pack «Piezas de plantillas». No se construye el «desmontaje» de MOGRT: no compensa.
- `trama/twins.py`: huella visual por miniatura (dHash 256 bits + 32×32 gris), con el damero de la transparencia tapado; parejas si coinciden tipo, proporción, duración (±3 %), distancia ≤20 bits y diferencia relativa al contenido ≤10 %. Búsqueda por franjas de 8 bits.
- Medida en la biblioteca real (6.652 miniaturas): huella de bits sola = 28.905 parejas (letras sobre negro y PNG sobre damero, falsos); con damero tapado y diferencia relativa = ~530, las de distinto formato casi todas el mismo efecto (.mov/.mp4, dos packs).
- Migración 0012 (`vprints`, `visual_twins`). La huella se calcula con el color y la luz (al generar la miniatura y en el trabajo `look`); las parejas se recalculan al terminar `look` y al terminar las vistas previas de un pack.
- Nada se fusiona: la ficha muestra «Posibles versiones» (formato, resolución, duración, tamaño, pack); el filtro «Solo duplicados y candidatos» las incluye; cada pack muestra «¡Epa, esto ya lo tenías!» con idénticos en otro pack y posibles versiones.
- Pruebas: 52/52.

## MOGRT: «Míralo en vídeo» (2026-09-29)
- Comprobado: un MOGRT no trae la animación renderizada (solo portada, proyecto de After Effects y materiales; la carpeta *Thumbnails* son las miniaturas de los huecos de vídeo, no fotogramas de la animación) y el bundle no trae vídeos de muestra; solo un Tutorial.mp4 por colección de títulos. No hay forma de reproducirlo sin Adobe.
- La ficha de un MOGRT ofrece «Míralo en vídeo»: el tutorial de su colección (vídeo en la misma carpeta de producto, fuera de los materiales) y el mismo efecto en vídeo en el resto de la biblioteca, buscado por las palabras de su nombre con sinónimos («Paper Rip» ↔ «Paper Tear»); con una sola palabra significativa no se busca (saldría cualquier cosa).
- Pruebas: 53/53.

## Etiquetas en las tarjetas (2026-09-29)
- Cada tarjeta muestra hasta 3 etiquetas de contenido bajo el título: primero las de la IA (✦, dicen qué es), luego las de carpeta y las propias. Formato y color no se repiten ahí (ya se ven en la miniatura y las insignias).
- Un toque en una etiqueta la añade al filtro (se combinan); las elegidas se resaltan en todas las tarjetas. Altura de fila de la galería virtual ajustada (TITLE_H 74).

## Modo presentación (2026-09-29)
- Para grabar o enseñar la biblioteca: oculta avisos técnicos (errores de análisis, «en packs», «prov.», banner de vistas previas, cerrar sesión) y la sección Ajustes, y la galería muestra solo recursos ya analizados (nada roto a la vista).
- Se activa en Ajustes → «Modo presentación», con Alt+P o con `?presentacion=1` en la dirección; se recuerda en el navegador (localStorage, con fallback). Para salir: Alt+P, o «✕ Salir de presentación», que aparece al pasar el ratón por abajo a la izquierda.

## ZIP anidados y presets de DaVinci (2026-10-04)
- Rastreo de los 110 ZIP anidados de la biblioteca (13,4 GB, descargas de plantillas): 1.745 MOGRT, 1.062 MP4, 510 GIF, 247 LUT .cube, ~1.800 imágenes, 57 WAV; ningún .drfx/.setting.
- `read_index` cataloga el contenido de los ZIP anidados, un nivel (`carpeta/plantilla.zip!/dentro/archivo`), con las mismas comprobaciones de seguridad; un ZIP más adentro no se abre. La extracción saca el anidado a un temporal una vez por lote (`_nested_zip` / `close_nested`).
- Títulos: el ZIP anidado cuenta como carpeta y se le quita el sufijo de descarga («vhs-transitions-2025-…-utc» → «Vhs Transitions»).
- Formatos de DaVinci reconocidos: `.preset` (ajustes del proyecto) y `.setting` (Fusion), además de `.drfx`.
- Pruebas: 54/54.
- Tras indexar los anidados: ~5.400 recursos nuevos (2.278 imágenes, 2.105 plantillas/LUT, 1.003 vídeos, 57 audios); vistas previas sin fallos (66 .prproj/.aep sin vista previa posible).
- Incidencia: las parejas de posibles versiones saltaron de 530 a 142.860. Causa: ~500 GIF de vista previa cuyo primer fotograma está en blanco → miniaturas iguales. Arreglo: la miniatura de un GIF animado sale del fotograma central (receta thumb-v2) y se descartan las huellas con más de 20 parejas (`MAX_TWINS`). Pruebas: 56/56.
