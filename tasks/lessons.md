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
- **Probar la imagen en el Mac antes del servidor sirvió.** El contenedor arrancaba pero sin FFmpeg (permisos de static-ffmpeg con usuario sin privilegios). Por SSH, Docker Desktop no puede abrir el llavero: usar un `DOCKER_CONFIG` temporal.
- **Antes de dar un archivo por «dañado», mirarlo.** De 33 errores, 22 eran `._` de macOS (no recursos) y los otros se confirmaron abriendo los bytes (todo a ceros, o cortado en 1 MiB). Así la lista para reclamar al vendedor es cierta.
- **`docker compose` interpreta `$` en `env_file`.** Una huella PBKDF2 (`pbkdf2$310000$…`) llegaba rota al contenedor; solo un warning lo delataba. Escapar como `$$` y comprobar la firma dentro del contenedor.
- **Un SQLite en WAL no se abre en un montaje de solo lectura.** Para restaurar un snapshot, montarlo con escritura para el usuario del contenedor.
- **Un healthcheck que no toca lo importante miente.** `/api/auth/status` respondía 200 con el proceso sin descriptores; el chequeo de salud debe abrir la base de datos y un archivo.
- **Conexiones por hilo en un servidor web = fuga.** Los hilos del pool mueren y nacen; lo que se guarda por hilo hay que cerrarlo cuando el hilo muere.
