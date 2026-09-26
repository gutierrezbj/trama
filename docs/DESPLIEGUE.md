# Despliegue en el Servidor 1 (estándar JRGB)

Encargo del propietario (26 sep 2026): TRAMA como herramienta interna en el **Servidor 1**
(`72.62.41.234`), offset **+260** reservado en el Catálogo de Infraestructura JRGB, dominio
`trama.jrgblanco.com` (registro A creado por el propietario en Hostinger el 26 sep 2026).

## Modelo
- Un contenedor `trama-app` (interfaz compilada + API + worker + FFmpeg estático), publicado solo en
  `127.0.0.1:3260` → 8765. Nunca en `0.0.0.0`.
- nginx del servidor con HTTPS de Let's Encrypt (Certbot) delante: `deploy/nginx-trama.jrgblanco.com.conf`.
- `TRAMA_AUTH_MODE=password` + `TRAMA_COOKIE_SECURE=1`: nada del catálogo, vistas previas ni
  originales sin sesión. `python -m trama serve` se niega a escuchar fuera de loopback sin contraseña.
- Datos en el volumen `trama-data` (`/data`): catálogo, derivados, caché de extracción (máx. 5 GB),
  respaldos y credenciales de Drive.
- Originales: los packs se leen del Google Drive del propietario por rangos. Las carpetas locales del
  PC quedan «offline» en el servidor (la ficha lo dice).

## Pasos
1. **Código**: `git clone https://github.com/gutierrezbj/trama /opt/apps/trama`.
2. **Configuración**: copiar `deploy/env.servidor.example` a `/opt/apps/trama/.env` (permisos 600) y
   rellenar `TRAMA_PASSWORD_HASH` (generado con `python -m trama set-password`).
3. **Arranque**: `docker compose up -d --build` en `/opt/apps/trama`. Comprobar
   `docker ps | grep trama-app` (healthy) y `curl -s 127.0.0.1:3260/api/auth/status`.
4. **Catálogo**: en el PC, `python -m trama backup` (snapshot con catálogo y vistas previas);
   copiarlo al servidor y restaurarlo con el contenedor parado:
   `docker compose run --rm app python -m trama restore /data/import/<snapshot> --yes`.
5. **Drive**: copiar `client_secret.json` y `token.json` a `/data/drive/` (permisos 600). El token
   actual se renueva solo; para volver a conectar desde el servidor hace falta un cliente OAuth
   «Aplicación web» con el URI `https://trama.jrgblanco.com/api/drive/auth/callback`.
6. **nginx**: copiar `deploy/nginx-trama.jrgblanco.com.conf` a `/etc/nginx/sites-available/`,
   enlazar en `sites-enabled`, `nginx -t` y recargar.
7. **HTTPS** (lo ejecuta el propietario): `certbot --nginx -d trama.jrgblanco.com`.
8. **Monitorización**: `/opt/scripts/healthcheck.sh` → `"TRAMA|trama-app|docker"`; SA99 →
   `sa99.servers.vps-prod.projects.TRAMA = {containers: ["trama-app"], domain: "trama.jrgblanco.com"}`
   y reflejarlo en `SEED_SERVERS`.
9. **Cierre**: Catálogo de Infraestructura (secciones 2, 4 y 7), Manifiesto SDD-JRGB y Kickoff en Notion.

## Comprobaciones
- Seguridad: `ss -tlnp | grep docker-proxy | grep 0.0.0.0` vacío.
- `curl -I https://trama.jrgblanco.com/api/assets` → 401 sin sesión.
- Inicio de sesión, vistas previas visibles, extracción de un recurso desde Drive y descarga del original.
- Respaldo diario: `docker compose exec app python -m trama backup` en cron.
