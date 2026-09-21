# ADR-002 — Packs ZIP, identidad provisional y extracción selectiva (E2)

Estado: aceptado (2026-09-21). Complementa ADR-001.

## Contexto
El pack de compra son 72 ZIP (141 GB) descargados de Google Drive en partes. Catalogarlo exigía
verlo entero sin extraerlo y sin duplicar 141 GB en disco; el disco tiene ~140 GB libres.

## Decisiones
1. **Indexar sin extraer.** Un `Pack` es un ZIP dentro de una raíz permitida; `PackEntry` es cada
   archivo interno con tamaño, tamaño comprimido y crc32 leídos del directorio central. Indexar los
   72 ZIP tarda segundos y no escribe nada fuera del catálogo.
2. **Seguridad del ZIP** antes de crear nada: se rechazan rutas absolutas o con unidad, `..`,
   más de 32 niveles, enlaces simbólicos, entradas de más de 16 GB, relaciones de compresión
   > 400 en archivos de más de 1 MB y métodos de compresión no soportados. Los ZIP anidados no se
   abren. Al extraer se verifica en streaming que los bytes escritos no superen el tamaño declarado
   (zip bomb) y que el destino quede dentro de la caché del pack.
3. **Identidad provisional.** Cada entrada catalogada obtiene una `AssetVersion` con clave
   `prov:<crc32>:<tamaño>` e `identity_kind = provisional`. Dos entradas con la misma clave comparten
   versión y ficha como *candidatas* a duplicado. La ficha (UUID) nace ya y sobrevive a la extracción.
4. **Confirmación por SHA-256 al extraer.** Si el hash coincide con una versión existente, la
   provisional se funde en ella: ubicaciones y entradas se repuntan; la ficha provisional se retira
   solo si no tiene ediciones humanas ni pertenencias; si las tiene, se conserva enlazada con
   `duplicate_of`. Nunca se borra un archivo. Si no coincide, la provisional pasa a definitiva.
5. **Extracción selectiva a caché** (`%LOCALAPPDATA%\TRAMA\cache\packs\<pack>\...`), por entrada,
   carpeta o pack, como trabajo cancelable con progreso por bytes. Límites: `TRAMA_CACHE_MAX_GB`
   (30) y `TRAMA_MIN_FREE_GB` (10); al superarlos el lote se detiene con error legible y conserva lo
   extraído. Concurrencia: una extracción y un índice a la vez, análisis/derivados en paralelo.
6. **Liberar caché** borra copias extraídas y devuelve la ubicación a `archived`; los derivados y
   la ficha se conservan. Descargar un original archivado lo extrae bajo demanda (solo esa entrada).
7. **Galería virtualizada**: solo se montan las filas visibles y las páginas (120) se piden según
   el desplazamiento; el total lo da la API. 8482 fichas → ~27 tarjetas montadas.
8. **Formatos sin preview genérica**: plantillas, proyectos y documentos se catalogan con la
   aplicación necesaria (dato declarado) y, si hay un archivo hermano con el mismo nombre base que sea
   vídeo o imagen, se muestra como «preview del proveedor». Los LUT `.cube/.3dl` generan una
   demostración antes/después sobre una imagen sintética (`testsrc2`), rotulada como demostración.
9. **Inventarios privados**: CSV por pack en el directorio de datos, nunca en el repositorio.

## Consecuencias
- El catálogo completo cabe en SQLite (9213 entradas, ~8500 fichas) y responde en cientos de ms.
- La identidad provisional es honesta pero débil: la interfaz la marca «prov.» hasta extraer.
- E3 deberá replicar derivados y catálogo, no la caché (que es reconstruible desde los ZIP).
