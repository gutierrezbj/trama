# Encargo inicial de construcción
## Objetivo
Construir TRAMA, biblioteca privada de recursos para producción audiovisual bajo identidad JRGB.
Problema: el propietario tiene miles de recursos, pero sus nombres y carpetas no permiten entenderlos ni elegirlos.
Éxito: encontrar un recurso sin recordar el nombre técnico, previsualizarlo, añadirlo a una selección y obtener su original.

## Orden de trabajo
1. Inspeccionar repositorio y entorno local, disponibilidad de Node, Python y FFmpeg, y las muestras autorizadas.
2. Revisar la arquitectura propuesta y registrar ADR-001 con decisiones y dependencias concretas. Las versiones deben verificarse al implementar.
3. Implementar E1 de tasks/todo.md completo. No quedarse en una maqueta con botones sin función.
4. Verificar recorrido real, comparar capturas con la dirección visual y entregar instrucciones reproducibles.

## Autorización del encargo
Preparar e implementar E1 local en este proyecto. Los siguientes incrementos quedan planificados.
No requiere desplegar ni abrir acceso público. No requiere subir o extraer el pack completo.
Si no están disponibles las muestras, pedir su ubicación local; no sustituirlas por recursos inventados como si fueran las muestras verificadas.

## Recorrido E1
Elegir carpeta de muestras mediante mecanismo local real, analizar, generar previews, explorar y filtrar, inspeccionar ficha, editar descripción/etiquetas, guardar favoritos y selección, descargar original.
Puede usarse inicialmente configuración explícita de raíz local permitida y un selector de subcarpetas servido por backend.
Una página alojada remotamente no puede explorar por sí sola el disco C: del usuario. El acceso local requiere proceso local o una selección/subida explícita.

## Entrega
Código ejecutable, migraciones, configuración de ejemplo sin secretos, comandos de arranque comprobados, pruebas relevantes, capturas, BUILD_NOTES.md y tasks/todo.md actualizado.
Indicar qué funciona, qué está pendiente y qué se midió realmente. No afirmar Drive conectado, dominio publicado ni integración Escenda completada.
