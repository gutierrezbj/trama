# ADR-003 — Acceso privado, Google Drive y respaldos (E3)

Estado: aceptado (2026-09-21). Complementa ADR-001 y ADR-002.

## Contexto
El catálogo pasa a poder servirse fuera del PC (VPS + dominio, todavía sin desplegar). Nada del
catálogo, las previews ni los originales debe servirse sin autenticación; los originales deben
poder copiarse a Google Drive de forma reanudable y verificable; y el catálogo debe respaldarse con
snapshots consistentes cuya restauración esté ensayada.

## Decisiones
1. **Autenticación mínima y propia**: una contraseña del propietario (PBKDF2-SHA256, 310 000
   iteraciones) y una cookie de sesión firmada con HMAC (secreto generado en el directorio de datos),
   `HttpOnly`, `SameSite=Strict`, `Secure` detrás de HTTPS. Sin usuarios múltiples ni proveedores
   externos de identidad: un solo propietario. Bloqueo progresivo por IP tras 5 fallos, persistido en
   SQLite. Tokens portadores opcionales (`TRAMA_API_TOKENS`) para integraciones sin navegador (E4).
2. **Todo `/api/*` exige sesión** salvo `auth/status`, `auth/login` y el callback OAuth de Drive
   (que Google llama sin cookie, pero solo es útil con un `state` emitido por una sesión autenticada).
   Las respuestas de la API llevan `Cache-Control: no-store`. La interfaz estática se sirve siempre.
   El modo `off` se mantiene por defecto para el uso en loopback; `python -m trama check` avisa si se
   escucha fuera de loopback sin contraseña.
3. **Drive con alcance mínimo** `drive.file`: TRAMA solo ve los archivos que ella crea, en una carpeta
   «TRAMA» privada. OAuth con PKCE; `client_secret.json` y `token.json` solo en el servidor, fuera del
   repo. Nunca se crean enlaces compartidos; el original remoto se sirve en streaming a través de
   TRAMA con rangos.
4. **Subida reanudable y verificable como trabajo propio** (`drive_upload`): la sesión de subida y
   el offset se guardan en el payload del trabajo, de modo que un reinicio o un 5xx reanudan donde
   Drive dice haberse quedado; al terminar se compara el `md5Checksum` de Drive con el md5 local y,
   si no coinciden, se borra el remoto y el trabajo falla. Solo entonces se crea la ubicación
   `kind=drive`. Subir es distinto de catalogar: no altera fichas ni derivados.
5. **Estado explícito de disponibilidad**: `available` significa copia local en este equipo;
   `remote_available`, copia verificada en Drive. Un original que solo está en un ordenador apagado
   aparece como «fuente offline», nunca como disponible.
6. **Respaldos**: snapshot = copia del catálogo con la API de copia de SQLite (consistente aunque
   haya escrituras) + derivados + manifiesto con SHA-256 y recuentos, en `TRAMA_BACKUP_DIR`; retención
   `TRAMA_BACKUP_KEEP`. Opcionalmente se comprime y sube a Drive. Restauración solo con el servidor
   parado y conservando lo anterior como `*.pre-restore-<fecha>`; verificación previa obligatoria.
   La caché de packs no se respalda (reconstruible desde los ZIP); los originales se respaldan
   subiéndolos a Drive, no dentro del snapshot.
7. **Despliegue y dominio no se ejecutan** (AGENTS.md): queda el plan en `docs/DESPLIEGUE.md`.
8. **Sin librerías de Google**: la API REST v3 se usa con httpx (ya presente), lo que permite probar
   todo el protocolo contra un servidor simulado en los tests.

## Consecuencias
- El adaptador de Drive está probado solo contra el simulador hasta que exista un cliente OAuth
  real; BUILD_NOTES lo declara así.
- Cambiar la contraseña exige editar `.env` y reiniciar; suficiente para un propietario.
- E4 puede autenticar a Escenda con un token portador sin tocar el modelo de sesión.
