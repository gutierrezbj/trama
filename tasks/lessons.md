# Lecciones aprendidas — TRAMA

- **Probar con el usuario real antes de dar algo por bueno.** La galería funcionaba, pero con 8.400
  recursos «sin extraer» sin imagen era inservible para buscar. Salió en la primera prueba del
  propietario, no en las pruebas automáticas (E3d).
- **Medir la lectura remota, no suponerla.** `RemoteFile` volvía a pedir bytes que ya tenía: 287
  peticiones y 1,1 MB/s para 152 MB. Contar peticiones y bytes bajados lo destapó (E3c).
- **Los packs comprados traen basura.** MP4 truncados («moov atom not found»), fuentes con licencia
  que prohíbe redistribuir. Marcarlos como error o mostrar la licencia, nunca esconderlo.
- **Los nombres de la interfaz tienen que ser los del usuario.** «Incorporar», «Copias y Drive» y
  «Añadir a selección» no se entendían; «Fuentes y packs», «Drive y copias» y «Guardar en proyecto» sí.
- **El Cuaderno de Protocolos JRGB va antes que el despliegue.** Proponer «despliego ya» sin
  clasificar el proyecto, reservar offset ni registrar en SA99 se salta el método de la casa.
- **No renombrar carpetas de originales ni para una prueba sin dejarlo apuntado.** Se hizo con OK del
  propietario para probar «solo Drive»; hay que cerrar esa situación (restaurar o borrar con OK).
- **La app de Claude puede parar el servidor de desarrollo por inactividad.** Para trabajos largos
  (subidas, vistas previas), arrancar `scripts\serve.cmd` en una terminal propia.
