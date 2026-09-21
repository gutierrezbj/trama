"""Punto de entrada: `python -m trama serve|migrate|check`."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trama", description="TRAMA — biblioteca de producción (E1 local)")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Arranca API + worker + interfaz en loopback")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    sub.add_parser("migrate", help="Aplica migraciones pendientes y termina")
    sub.add_parser("check", help="Comprueba configuración, raíces y FFmpeg")
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
        return 0

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        app = create_app(settings)
        host = args.host or settings.host
        port = args.port or settings.port
        print(f"TRAMA en http://{host}:{port}  (datos en {settings.data_dir})")
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
