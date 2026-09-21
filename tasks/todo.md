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

## E2 — Pack completo
- [ ] Inventarios privados, ZIP seguros y extracción selectiva (Pack/PackEntry en el modelo).
- [ ] Jobs persistentes cancelables, límites de disco y concurrencia.
- [ ] Duplicados confirmados por hash, relación con packs y ubicaciones.
- [ ] Galería que soporte el inventario completo sin cargar todos los vídeos (virtualización; hoy paginación de 60).
- [ ] Gestión honesta de plantillas, LUTs y formatos no soportados (hoy: se catalogan sin preview).

## E3 — Google Drive y acceso privado
- [ ] OAuth, adaptador Drive, transferencia reanudable y caché.
- [ ] Autenticación/autorización de catálogo, originales y previews.
- [ ] Respaldos y restauración probada.
- [ ] Despliegue y dominio solo mediante encargo específico.

## E4 — Integración Escenda
- [ ] Validar contrato con implementación actual de Escenda.
- [ ] API de consulta/selección/obtención y pruebas de contrato.
- [ ] Integración real sin editar Escenda dentro del encargo E1.

## Posterior
DJ V2 y marketplace no se implementan en esta etapa.
