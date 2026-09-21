# Despliegue privado (plan, no ejecutado)

`AGENTS.md` prohíbe desplegar o tocar DNS sin encargo específico. Este documento deja preparado el
procedimiento para que el despliegue en `trama.jrgblanco.com` sea un encargo corto y reproducible.
Nada de lo descrito aquí se ha ejecutado.

## Modelo
- Un solo proceso `python -m trama serve` ligado a `127.0.0.1:8765` en el servidor (VPS Linux).
- Proxy inverso con HTTPS delante (Caddy obtiene el certificado solo). Solo el proxy escucha en 443.
- `TRAMA_AUTH_MODE=password` + `TRAMA_COOKIE_SECURE=1`: nada de la API (catálogo, previews,
  originales) se sirve sin sesión. La interfaz estática sí, y muestra la pantalla de acceso.
- Los datos viven en `/var/lib/trama` (catálogo, derivados, caché, respaldos, token de Drive).
- Los originales locales del PC **no** están en el servidor: la ficha lo dice explícitamente
  («fuente offline»). El servidor sirve previews y, si el recurso se copió a Drive, el original en
  streaming desde Drive. Para catalogar packs en el servidor habría que subir los ZIP a una raíz
  permitida del propio servidor (fuera del alcance de este plan).

## Pasos previstos
1. Sistema: Debian/Ubuntu con Python 3.12+, Node solo para compilar la interfaz (o copiar `frontend/dist` ya compilado). FFmpeg: `apt install ffmpeg` o el estático del venv.
2. Usuario de servicio `trama`, repo en `/opt/trama`, venv en `/opt/trama/backend/.venv`, datos en `/var/lib/trama` (`TRAMA_DATA_DIR`).
3. `.env` en `/opt/trama/.env` con: `TRAMA_HOST=127.0.0.1`, `TRAMA_PORT=8765`, `TRAMA_AUTH_MODE=password`, `TRAMA_PASSWORD_HASH=…` (generado con `python -m trama set-password`), `TRAMA_COOKIE_SECURE=1`, `TRAMA_DATA_DIR=/var/lib/trama`, `TRAMA_ALLOWED_ROOTS=/srv/trama-fuentes` (vacía o con lo que se decida subir), `TRAMA_DRIVE_CLIENT_FILE=/var/lib/trama/drive/client_secret.json`, `TRAMA_DRIVE_REDIRECT_URI=https://trama.jrgblanco.com/api/drive/auth/callback`.
4. systemd:
   ```ini
   [Unit]
   Description=TRAMA
   After=network.target
   [Service]
   User=trama
   WorkingDirectory=/opt/trama/backend
   EnvironmentFile=/opt/trama/.env
   ExecStart=/opt/trama/backend/.venv/bin/python -m trama serve
   Restart=on-failure
   [Install]
   WantedBy=multi-user.target
   ```
5. Caddy (`/etc/caddy/Caddyfile`):
   ```
   trama.jrgblanco.com {
       reverse_proxy 127.0.0.1:8765
       encode gzip
       header { X-Frame-Options DENY; Referrer-Policy no-referrer }
   }
   ```
   DNS: registro A/AAAA de `trama.jrgblanco.com` al VPS (encargo específico).
6. Google Cloud: cliente OAuth «Aplicación web» con el URI de redirección anterior; `client_secret.json` al servidor con permisos 600. Conectar desde «Copias y Drive».
7. Respaldos: `python -m trama backup` en un cron diario (o «Crear y subir a Drive» desde la interfaz); `TRAMA_BACKUP_KEEP` según espacio. Restauración: parar el servicio, `python -m trama verify-backup <carpeta>`, `python -m trama restore <carpeta>`, arrancar.
8. Migrar el catálogo del PC al servidor: crear snapshot en el PC, copiarlo (scp) y restaurarlo en `/var/lib/trama`. Las ubicaciones locales del PC quedarán «offline» en el servidor; las de Drive seguirán disponibles.

## Comprobaciones tras desplegar
- `curl -I https://trama.jrgblanco.com/api/assets` → 401 sin sesión.
- Inicio de sesión desde el navegador, previews visibles, descarga de un original desde Drive.
- `python -m trama check` en el servidor: modo password con contraseña, Drive configurado y conectado.
