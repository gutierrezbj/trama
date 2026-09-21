"""Respaldos: snapshot consistente del catálogo (API de copia de SQLite) + derivados, con manifiesto,
retención y restauración ensayada. La caché de packs no se respalda (se reconstruye desde los ZIP);
los originales se respaldan aparte, subiéndolos a Drive como tarea propia (drive.py)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .db import Database, new_id, now_iso
from . import __version__

MANIFEST = "manifest.json"


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_tree(src: Path, dst: Path) -> tuple[int, int]:
    files = size = 0
    if not src.exists():
        return 0, 0
    for p in src.rglob("*"):
        if p.is_file() and not p.name.endswith(".part"):
            rel = p.relative_to(src)
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)
            files += 1
            size += p.stat().st_size
    return files, size


def create_backup(db: Database, settings: Settings, label: str = "") -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = settings.backups_dir / f"trama-{stamp}{('-' + label) if label else ''}"
    tmp = folder.with_name(folder.name + ".part")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    # Copia consistente aunque haya escrituras concurrentes (WAL): API backup de SQLite.
    dest_db = tmp / "catalogo.sqlite"
    dst = sqlite3.connect(str(dest_db))
    try:
        db.conn.backup(dst)
    finally:
        dst.close()  # `with` en sqlite3 no cierra la conexión; en Windows bloquearía el rename
    check = sqlite3.connect(str(dest_db))
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        assets = check.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        shutil.rmtree(tmp)
        raise BackupError(f"La copia del catálogo no pasa integrity_check: {ok}")
    files, size = _copy_tree(settings.derivatives_dir, tmp / "derivados")
    db_sha = _sha256(dest_db)
    manifest = {
        "trama_version": __version__,
        "created_at": now_iso(),
        "db_sha256": db_sha,
        "db_bytes": dest_db.stat().st_size,
        "derivatives_files": files,
        "derivatives_bytes": size,
        "assets": assets,
        "note": "La caché de packs no se incluye: se reconstruye desde los ZIP. Los originales locales no se incluyen.",
    }
    (tmp / MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(folder)
    backup_id = new_id("bak")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO backups(id, path, created_at, db_sha256, db_bytes, derivatives_bytes, derivatives_files, assets, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'done')",
            (backup_id, str(folder), manifest["created_at"], db_sha, manifest["db_bytes"], size, files, assets),
        )
    prune_backups(db, settings)
    return {"id": backup_id, "path": str(folder), **manifest}


def prune_backups(db: Database, settings: Settings) -> list[str]:
    rows = db.query("SELECT id, path FROM backups WHERE status IN ('done','uploaded') ORDER BY created_at DESC")
    removed = []
    for row in rows[settings.backup_keep:]:
        path = Path(row["path"])
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        with db.tx() as conn:
            conn.execute("DELETE FROM backups WHERE id = ?", (row["id"],))
        removed.append(row["id"])
    return removed


def list_backups(db: Database) -> list[dict]:
    out = []
    for row in db.query("SELECT * FROM backups ORDER BY created_at DESC"):
        d = dict(row)
        d["present"] = Path(d["path"]).is_dir() and (Path(d["path"]) / MANIFEST).is_file()
        out.append(d)
    return out


def verify_backup(folder: Path) -> dict:
    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        raise BackupError("Falta manifest.json en el respaldo")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db_file = folder / "catalogo.sqlite"
    if not db_file.is_file():
        raise BackupError("Falta catalogo.sqlite en el respaldo")
    if _sha256(db_file) != manifest["db_sha256"]:
        raise BackupError("El catálogo del respaldo no coincide con su SHA-256: respaldo corrupto")
    check = sqlite3.connect(str(db_file))
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"El catálogo del respaldo no es una base SQLite válida: {exc}") from exc
    finally:
        check.close()
    if ok != "ok":
        raise BackupError(f"integrity_check del respaldo: {ok}")
    present = sum(1 for p in (folder / "derivados").rglob("*") if p.is_file()) if (folder / "derivados").exists() else 0
    manifest["derivatives_present"] = present
    return manifest


def restore_backup(settings: Settings, folder: Path) -> dict:
    """Restaura con el servidor PARADO: conserva lo actual en *.pre-restore antes de sustituirlo."""
    manifest = verify_backup(folder)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    db_path = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.rename(p.with_name(f"{p.name}.pre-restore-{stamp}"))
    shutil.copy2(folder / "catalogo.sqlite", db_path)
    deriv = settings.derivatives_dir
    if deriv.exists():
        deriv.rename(deriv.with_name(f"{deriv.name}.pre-restore-{stamp}"))
    if (folder / "derivados").exists():
        shutil.copytree(folder / "derivados", deriv)
    else:
        deriv.mkdir(parents=True, exist_ok=True)
    return {"restored_from": str(folder), "kept_previous_as": f"*.pre-restore-{stamp}", **manifest}
