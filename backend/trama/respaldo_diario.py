"""Respaldo diario del catálogo: copia consistente de la base (API de copia de SQLite), comprimida con gzip,
en <data>/respaldos/diario, conservando las últimas N. Una vez por semana sube además la copia del día a la
carpeta TRAMA/Respaldos de Drive y deja allí las últimas M.

Solo el catálogo (~200 MB, ~50 MB comprimido): los derivados (miniaturas, vistas previas) se rehacen desde
los packs y los originales ya viven en Drive. Pensado para cron: `python -m trama respaldo-diario`.
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings

PREFIJO = "catalogo-"
SUFIJO = ".sqlite.gz"
SUBCARPETA_DRIVE = "Respaldos"


def _copias(carpeta: Path) -> list[Path]:
    return sorted(carpeta.glob(f"{PREFIJO}*{SUFIJO}"))


def crear(settings: Settings, ahora: datetime | None = None) -> Path:
    ahora = ahora or datetime.now(timezone.utc)
    carpeta = settings.data_dir / "respaldos" / "diario"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{PREFIJO}{ahora:%Y-%m-%d}{SUFIJO}"
    tmp = carpeta / (destino.name + ".tmp")
    plano = carpeta / "_copia.sqlite"
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(plano)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(plano)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        plano.unlink(missing_ok=True)
        raise RuntimeError(f"La copia no pasó integrity_check: {ok}")
    with open(plano, "rb") as fh, gzip.open(tmp, "wb", compresslevel=6) as gz:
        shutil.copyfileobj(fh, gz, 4 * 1024 * 1024)
    plano.unlink()
    tmp.replace(destino)
    return destino


def podar(carpeta: Path, conservar: int) -> list[Path]:
    copias = _copias(carpeta)
    fuera = copias[:-conservar] if conservar > 0 else []
    for p in fuera:
        p.unlink()
    return fuera


def subir_semanal(settings: Settings, copia: Path, conservar_drive: int, ahora: datetime | None = None, transport=None) -> str | None:
    """Sube `copia` si en Drive no hay ninguna de los últimos 7 días. Devuelve el id subido o None."""
    from .drive import DriveClient, mime_for

    ahora = ahora or datetime.now(timezone.utc)
    client = DriveClient(settings, transport)
    try:
        folder = client.ensure_subfolder(SUBCARPETA_DRIVE, client.ensure_folder())
        hay = sorted((f for f in client.list_children(folder) if f["name"].startswith(PREFIJO)), key=lambda f: f["name"])
        limite = f"{PREFIJO}{(ahora - timedelta(days=6)):%Y-%m-%d}"
        if hay and hay[-1]["name"] >= limite:
            return None
        size = copia.stat().st_size
        session = client.start_upload(copia.name, size, mime_for(".gz"), folder, {"trama": "respaldo-diario"})
        meta = client.upload_file(copia, session, size, 0)
        hay.append({"id": meta.get("id"), "name": copia.name})
        for viejo in hay[:-conservar_drive] if conservar_drive > 0 else []:
            # a la papelera de Drive (no borrado definitivo): Google la vacía sola a los 30 días
            client._api("PATCH", f"/drive/v3/files/{viejo['id']}", json={"trashed": True})
        return meta.get("id")
    finally:
        client.close()


def ejecutar(settings: Settings, conservar: int = 14, conservar_drive: int = 8, drive: bool = True) -> dict:
    copia = crear(settings)
    fuera = podar(copia.parent, conservar)
    res = {"copia": str(copia), "mb": round(copia.stat().st_size / 2**20, 1), "borradas": [p.name for p in fuera], "drive": None}
    if drive:
        try:
            res["drive"] = subir_semanal(settings, copia, conservar_drive) or "ya había una de esta semana"
        except Exception as exc:  # Drive caído o desconectado: la copia local ya está hecha
            res["drive"] = f"error: {exc}"
    return res
