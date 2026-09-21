# Plan de TRAMA
## E0 — Definición
- [x] Alcance V1 audiovisual; DJ reservado a V2.
- [x] Nombre TRAMA, firma JRGB y destino de dominio.
- [x] Dirección visual y dos referencias.
- [x] Arquitectura propuesta y encargo inicial.
- [x] ADR-001: validar stack y entorno, fijar versiones al implementar → `docs/ADR-001-stack-e1.md`.

## E1 — Piloto local real (entregado 2026-09-20, ver BUILD_NOTES.md)
- [x] Arranque documentado de interfaz/API/worker y migraciones (`scripts\setup.cmd`, `scripts\serve.cmd`, `python -m trama check|migrate|serve`).
- [x] Incorporar las tres muestras y una colección pequeña elegida del pack (NEON FX: PARTICULAS + REDES SOCIAIS, 26 archivos extraídos fuera del repo).
- [x] Análisis real, miniaturas, proxies y preview de alfa (tres fondos: oscuro, claro, cuadriculado; alfa detectado por formato y medido por uso).
- [x] Galería, filtros, búsqueda, inspector accesible (Escape cierra y devuelve el foco; controles con nombre; hover silencioso y sin autoplay con movimiento reducido).
- [x] Etiquetas/descripción editables, favoritos, selecciones y obtención de originales (descarga con nombre original y rangos HTTP).
- [x] Persistencia al reiniciar y reimportación sin duplicar fichas (probado en `backend/tests`).
- [x] Error de análisis visible; fuente offline conservando catálogo (estado por ubicación, aviso en ficha, filtro de disponibilidad).
- [x] Verificación visual contra boceto y recorrido completo documentado (BUILD_NOTES.md, `docs/capturas/`).
- [ ] Pendiente menor: elección definitiva del símbolo de marca (cabecera intercambiable; hoy rectángulo amarillo, sin redibujar el pez JRGB).
- [ ] Pendiente menor: descripción "inferida" no se genera (sin IA en E1); solo hay descripciones humanas o vacías.

Aceptación: recorrer incorporar → explorar → preview → selección → original con bytes reales.
Probar rotación de la transición, duración del humo, conservación de alfa, reproducción WAV, reintentos y persistencia.
No modificar los originales. Medir rendimiento en el equipo real; no prometer tiempos sin medición.

## E2 — Pack completo (entregado 2026-09-21, ver BUILD_NOTES.md)
- [x] Inventarios privados, ZIP seguros y extracción selectiva (Pack/PackEntry en el modelo, `docs/ADR-002-packs-e2.md`).
- [x] Jobs persistentes cancelables, límites de disco y concurrencia (caché máx., espacio libre mínimo, una extracción a la vez).
- [x] Duplicados confirmados por hash, relación con packs y ubicaciones (identidad provisional crc32+tamaño → SHA-256 al extraer; `duplicate_of`; `/api/duplicates`).
- [x] Galería que soporta el inventario completo sin cargar todos los vídeos (virtualización por filas, páginas de 120 bajo demanda).
- [x] Gestión honesta de plantillas, LUTs y formatos no soportados (aplicación necesaria, preview del proveedor si existe, demostración de LUT rotulada).
- [ ] Pendiente menor: vista dedicada de duplicados (hoy: filtro «Solo duplicados y candidatos» y `/api/duplicates`).
- [ ] Pendiente menor: el pack real no trae MOGRT/AEP con vídeo hermano; el enlace de preview del proveedor solo está probado con fixtures.

## E3 — Google Drive y acceso privado (entregado 2026-09-21, ver BUILD_NOTES.md)
- [x] OAuth (PKCE, alcance mínimo `drive.file`), adaptador Drive REST v3 sobre httpx, subida reanudable con verificación md5 como trabajo propio, descarga en streaming con rangos (`docs/ADR-003-acceso-drive-e3.md`). Probado contra un servidor simulado: **no hay cliente OAuth real todavía**; la interfaz lo indica como «no configurado».
- [x] Autenticación/autorización de catálogo, originales y previews: modo contraseña (PBKDF2 + cookie firmada), bloqueo por intentos, tokens portadores; toda la API exige sesión.
- [x] Respaldos y restauración probada: snapshots consistentes con manifiesto y SHA-256, retención, verificación, restauración ensayada en test y comando `restore`; subida opcional del snapshot a Drive.
- [ ] Despliegue y dominio solo mediante encargo específico → plan en `docs/DESPLIEGUE.md`, sin ejecutar.
- [ ] Pendiente: crear el cliente OAuth en Google Cloud (propietario) y conectar Drive de verdad; primera subida real medida.
- [ ] Pendiente menor: catalogar carpetas ya existentes en Drive (requeriría alcance `drive.readonly`; fuera de E3).

## E4 — Integración Escenda
- [ ] Validar contrato con implementación actual de Escenda.
- [ ] API de consulta/selección/obtención y pruebas de contrato.
- [ ] Integración real sin editar Escenda dentro del encargo E1.

## Posterior
DJ V2 y marketplace no se implementan en esta etapa.
