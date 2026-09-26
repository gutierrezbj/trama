"""Punto de entrada: `python -m trama serve|migrate|check`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trama", description="TRAMA — biblioteca de producción (E1 local)")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Arranca API + worker + interfaz en loopback")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    sub.add_parser("migrate", help="Aplica migraciones pendientes y termina")
    sub.add_parser("check", help="Comprueba configuración, raíces y FFmpeg")
    sub.add_parser("set-password", help="Genera TRAMA_PASSWORD_HASH para .env (pide la contraseña, no la guarda)")
    bk = sub.add_parser("backup", help="Crea un snapshot consistente del catálogo y los derivados")
    bk.add_argument("--label", default="")
    rs = sub.add_parser("restore", help="Restaura un snapshot (con el servidor parado)")
    rs.add_argument("folder")
    rs.add_argument("--yes", action="store_true", help="No pedir confirmación")
    vb = sub.add_parser("verify-backup", help="Comprueba la integridad de un snapshot")
    vb.add_argument("folder")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    settings.ensure_dirs()

    if args.command == "migrate":
        from .db import Database

        db = Database(settings.db_path)
        applied = db.migrate()
        print(f"Base de datos: {settings.db_path}")
        print(f"Migraciones aplicadas: {applied or 'ninguna nueva'}")
        return 0

    if args.command == "check":
        from .media import MediaError, resolve_tools

        print(f"Archivo .env: {settings.env_file or 'no encontrado (usando valores por defecto/entorno)'}")
        print(f"Datos de ejecución: {settings.data_dir}")
        print("Raíces permitidas:")
        if not settings.allowed_roots:
            print("  (ninguna) → define TRAMA_ALLOWED_ROOTS en .env")
        for root in settings.allowed_roots:
            print(f"  {'OK ' if root.is_dir() else 'NO '} {root}")
        try:
            tools = resolve_tools(settings)
            print(f"ffmpeg : {tools.ffmpeg}\n         {tools.ffmpeg_version}")
            print(f"ffprobe: {tools.ffprobe}\n         {tools.ffprobe_version}")
        except MediaError as exc:
            print(f"FFmpeg: {exc}")
            return 1
        print(f"Acceso: modo {settings.auth_mode}" + ("" if settings.auth_mode != "password" else (" (contraseña configurada)" if settings.password_hash else " ¡SIN CONTRASEÑA! define TRAMA_PASSWORD_HASH")))
        if settings.auth_mode != "password" and settings.host not in ("127.0.0.1", "localhost", "::1"):
            print("AVISO: la API escucha fuera de loopback sin autenticación. Usa TRAMA_AUTH_MODE=password.")
        print(f"Drive: {'configurado (' + str(settings.drive_client_file) + ')' if settings.drive_configured else 'no configurado (sin client_secret.json)'}"
              + (", conectado" if settings.drive_token_file.is_file() else ""))
        print(f"Respaldos: {settings.backups_dir} (se conservan {settings.backup_keep})")
        return 0

    if args.command == "set-password":
        import getpass

        from .auth import hash_password

        pw = getpass.getpass("Contraseña de TRAMA: ")
        if len(pw) < 10:
            print("Usa al menos 10 caracteres.")
            return 1
        if pw != getpass.getpass("Repite la contraseña: "):
            print("No coinciden.")
            return 1
        print("Añade estas líneas a .env (y reinicia):")
        print("TRAMA_AUTH_MODE=password")
        print(f"TRAMA_PASSWORD_HASH={hash_password(pw)}")
        return 0

    if args.command == "backup":
        from .backup import create_backup
        from .db import Database

        db = Database(settings.db_path)
        db.migrate()
        result = create_backup(db, settings, args.label)
        print(f"Respaldo: {result['path']}\n  fichas: {result['assets']}  derivados: {result['derivatives_files']} ({result['derivatives_bytes'] // 2**20} MB)  sha256 catálogo: {result['db_sha256'][:16]}…")
        return 0

    if args.command == "verify-backup":
        from .backup import BackupError, verify_backup

        try:
            m = verify_backup(Path(args.folder))
        except BackupError as exc:
            print(f"NO válido: {exc}")
            return 1
        print(f"Válido: {m['assets']} fichas, {m['derivatives_present']}/{m['derivatives_files']} derivados presentes, creado {m['created_at']}")
        return 0

    if args.command == "restore":
        from .backup import BackupError, restore_backup

        if not args.yes:
            answer = input(f"Se sustituirá el catálogo en {settings.data_dir} por {args.folder}. El servidor debe estar parado. ¿Continuar? [s/N] ")
            if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
                print("Cancelado.")
                return 1
        try:
            r = restore_backup(settings, Path(args.folder))
        except BackupError as exc:
            print(f"Error: {exc}")
            return 1
        print(f"Restaurado desde {r['restored_from']} ({r['assets']} fichas). Lo anterior se conservó como {r['kept_previous_as']}.")
        return 0

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        host = args.host or settings.host
        port = args.port or settings.port
        if host not in ("127.0.0.1", "localhost", "::1") and (settings.auth_mode != "password" or not settings.password_hash):
            print(f"Rechazado: escuchar en {host} exige TRAMA_AUTH_MODE=password y TRAMA_PASSWORD_HASH.")
            return 2
        app = create_app(settings)
        print(f"TRAMA en http://{host}:{port}  (datos en {settings.data_dir})")
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
