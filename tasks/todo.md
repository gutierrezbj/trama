# Plan de TRAMA
## E0 — Definición
- [x] Alcance V1 audiovisual; DJ reservado a V2.
- [x] Nombre TRAMA, firma JRGB y destino de dominio.
- [x] Dirección visual y dos referencias.
- [x] Arquitectura propuesta y encargo inicial.
- [ ] ADR-001: validar stack y entorno, fijar versiones al implementar.

## E1 — Piloto local real (siguiente trabajo)
- [ ] Arranque documentado de interfaz/API/worker y migraciones.
- [ ] Incorporar las tres muestras y una colección pequeña elegida del pack.
- [ ] Análisis real, miniaturas, proxies y preview de alfa.
- [ ] Galería, filtros, búsqueda, inspector accesible.
- [ ] Etiquetas/descripción editables, favoritos, selecciones y obtención de originales.
- [ ] Persistencia al reiniciar y reimportación sin duplicar fichas.
- [ ] Error de análisis visible; fuente offline conservando catálogo.
- [ ] Verificación visual contra boceto y recorrido completo documentado.

Aceptación: recorrer incorporar → explorar → preview → selección → original con bytes reales.
Probar rotación de la transición, duración del humo, conservación de alfa, reproducción WAV, reintentos y persistencia.
No modificar los originales. Medir rendimiento en el equipo real; no prometer tiempos sin medición.

## E2 — Pack completo
- [ ] Inventarios privados, ZIP seguros y extracción selectiva.
- [ ] Jobs persistentes cancelables, límites de disco y concurrencia.
- [ ] Duplicados confirmados por hash, relación con packs y ubicaciones.
- [ ] Galería que soporte el inventario completo sin cargar todos los vídeos.
- [ ] Gestión honesta de plantillas, LUTs y formatos no soportados.

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
