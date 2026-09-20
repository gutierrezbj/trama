# Producto y experiencia
## Alcance V1
VFX, overlays, transiciones, fondos, animación, imágenes, LUTs, plantillas, audio de producción y documentación asociada.
Colecciones organizan recursos. Selecciones reúnen recursos para una producción sin duplicar bytes.
El pack de compra mantiene procedencia; no determina por sí solo la categoría de cada archivo.

## Pantallas
- Explorar: vista principal, buscador, filtros combinables, galería paginada o virtualizada y ficha lateral.
- Colecciones: agrupaciones editables, un recurso puede pertenecer a varias.
- Mis selecciones: nombre, notas, orden y recursos; quitar un recurso no borra su original.
- Favoritos: persistentes.
- Incorporar: fuentes, lotes, progreso, errores, reintento y cancelación segura.
No añadir una portada de métricas que dificulte llegar a los recursos.

## Interacciones
Hover reproduce una sola preview visible, silenciada; teclado y táctil ofrecen reproducción explícita. Respetar movimiento reducido.
Seleccionar abre inspector y conserva scroll, filtros y búsqueda. Escape lo cierra; foco accesible.
Cambiar filtros no pierde selección guardada. Sin resultados ofrece limpiar filtros.
Datos desconocidos se muestran pendientes, nunca como cero ni falsa ausencia.
Estados independientes: original disponible, análisis pendiente/completo/fallido, preview pendiente/lista/no compatible/fallida.
Fuente desconectada mantiene ficha y derivados disponibles, pero señala que el original no puede obtenerse.

## Previews
Vídeo: proxy reproducible con duración y orientación correctas.
Alfa: fondos oscuro, claro y cuadriculado. Un MP4 aplanado no conserva alfa: usar derivados de fondo explícitos o una estrategia compatible verificada.
Audio: play/pausa, búsqueda temporal y waveform. Nunca autoplay audible.
LUT: antes/después sobre referencia, rotulado como demostración.
Plantilla: preview del proveedor si existe; mostrar aplicación requerida. No prometer renderizar MOGRT/AEP de forma genérica.
Transición: original reproducible; demostración entre planos separada y señalada.
No afirmar que un archivo es loop o recomendar un modo de fusión como hecho sin revisión.

## Búsqueda
E1 textual sobre nombres, descripciones y etiquetas, sin distinguir mayúsculas ni acentos.
Filtros por categoría, duración, orientación, presencia de alfa comprobada y disponibilidad.
Búsqueda semántica e identificación visual automática posteriores, con coste y procedencia visibles.
