"""Incorporación de carpetas locales: descubrir, inventariar, identificar por hash y encolar.

Reglas:
- Nunca se modifican, mueven ni renombran los originales.
- La identidad de bytes es el SHA-256 completo. Nombre+tamaño solo sirven para saltar el
  hash de archivos ya vistos sin cambios (misma ruta, tamaño y mtime).
- Reimportar es idempotente: un archivo ya conocido no crea una segunda ficha.
- Las ediciones humanas (título, descripción, etiquetas, categoría) no se sobrescriben.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable

from .config import MEDIA_EXTENSIONS, Settings, media_kind_for, source_id_for
from .db import Database, new_id, normalize_text, now_iso

CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"transi|transition|wipe|swipe", re.I), "transiciones"),
    (re.compile(r"overlay|grain|grano|dust|polvo|leak|light\s*leak|burn|scratch|film", re.I), "overlays"),
    (re.compile(r"fondo|background|backdrop|\bback\b|back\d|\bbg\b", re.I), "fondos"),
    (re.compile(r"\bluts?\b|\bcolor\b|grade|preset", re.I), "color"),
    (re.compile(r"mogrt|template|plantilla|title|lower\s*third|titulo", re.I), "plantillas"),
    (re.compile(r"anim|neon|scribble|cartoon|hud|hologram|objeto|kit|icon|logo|redes|social", re.I), "animacion"),
    (re.compile(r"vfx|smoke|humo|fire|fuego|explo|spark|particle|particul|glitch|energy|magic|action|efecto", re.I), "vfx"),
]


def infer_category(rel_path: str, media_kind: str, ext: str) -> str:
    if media_kind == "audio":
        return "audio"
    if media_kind == "image":
        return "imagenes"
    if ext in (".cube", ".3dl", ".look"):
        return "color"
    if ext in (".mogrt", ".aep", ".prproj", ".drp", ".drfx"):
        return "plantillas"
    if ext in (".pdf", ".txt", ".html"):
        return "documentacion"
    haystack = rel_path.replace("\\", "/")
    # Evaluar primero el nombre del archivo, luego las carpetas de más cercana a más lejana.
    parts = [Path(haystack).name] + list(reversed(Path(haystack).parent.parts))
    for part in parts:
        for pattern, category in CATEGORY_RULES:
            if pattern.search(part):
                return category
    return "vfx" if media_kind == "video" else "otros"


def clean_title(file_name: str) -> str:
    stem = Path(file_name).stem
    stem = re.sub(r"[_\.]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or file_name


def build_search_text(title: str, original_title: str, description: str, tags: list[str], rel_path: str) -> str:
    return normalize_text(" ".join([title, original_title, description, " ".join(tags), rel_path]))


def sha256_of(path: Path, progress: Callable[[int], None] | None = None, should_cancel: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            if progress:
                progress(len(chunk))
            if should_cancel and should_cancel():
                raise ImportCancelled()
    return digest.hexdigest()


class ImportCancelled(Exception):
    pass


def ensure_source(db: Database, root: Path) -> str:
    source_id = source_id_for(root)
    if db.one("SELECT id FROM sources WHERE id = ?", (source_id,)) is None:
        with db.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sources(id, kind, label, root_path, created_at) VALUES (?, 'local', ?, ?, ?)",
                (source_id, root.name or str(root), str(root.resolve()), now_iso()),
            )
    return source_id


def resolve_subpath(root: Path, sub_path: str) -> Path:
    """Resuelve una subruta relativa dentro de la raíz permitida, rechazando escapes."""
    root_resolved = root.resolve()
    candidate = (root_resolved / sub_path).resolve() if sub_path else root_resolved
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("La ruta queda fuera de la raíz permitida") from exc
    return candidate


def discover_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() != "__macosx"]
        for name in filenames:
            if name.startswith(".") or name.startswith("._"):
                continue
            if Path(name).suffix.lower() in MEDIA_EXTENSIONS:
                files.append(Path(dirpath) / name)
    files.sort()
    return files


def run_import(
    db: Database,
    settings: Settings,
    import_id: str,
    should_cancel: Callable[[], bool],
    on_progress: Callable[[dict], None],
) -> dict:
    row = db.one("SELECT * FROM imports WHERE id = ?", (import_id,))
    if row is None:
        raise RuntimeError("Importación inexistente")
    root = settings.source_for_id(row["source_id"])
    if root is None:
        raise RuntimeError("La fuente ya no está entre las raíces permitidas")
    if not root.exists():
        raise RuntimeError(f"La raíz no está accesible: {root}")
    folder = resolve_subpath(root, row["sub_path"])
    if not folder.is_dir():
        raise RuntimeError(f"La carpeta no existe: {folder}")

    files = discover_files(folder)
    stats = {"total_files": len(files), "processed": 0, "added": 0, "updated": 0, "unchanged": 0, "offline": 0, "errors": []}
    with db.tx() as conn:
        conn.execute("UPDATE imports SET total_files = ?, status = 'running', started_at = ? WHERE id = ?", (len(files), now_iso(), import_id))
    on_progress(dict(stats))

    seen_rel: set[str] = set()
    root_resolved = root.resolve()
    for path in files:
        if should_cancel():
            raise ImportCancelled()
        rel_path = path.resolve().relative_to(root_resolved).as_posix()
        seen_rel.add(rel_path)
        try:
            outcome = _ingest_file(db, row["source_id"], root_resolved, path, rel_path, should_cancel)
            stats[outcome] += 1
        except ImportCancelled:
            raise
        except Exception as exc:  # error por archivo: se registra y el lote continúa
            stats["errors"].append({"path": rel_path, "error": str(exc)})
        stats["processed"] += 1
        on_progress(dict(stats))

    # Ubicaciones bajo la carpeta importada que ya no existen → offline (no se borran).
    prefix = folder.resolve().relative_to(root_resolved).as_posix()
    prefix = "" if prefix == "." else prefix
    known = db.query("SELECT id, rel_path, status FROM locations WHERE source_id = ?", (row["source_id"],))
    now = now_iso()
    with db.tx() as conn:
        for loc in known:
            inside = loc["rel_path"] == prefix or (not prefix) or loc["rel_path"].startswith(prefix + "/")
            if inside and loc["rel_path"] not in seen_rel and loc["status"] != "offline":
                conn.execute("UPDATE locations SET status = 'offline' WHERE id = ?", (loc["id"],))
                stats["offline"] += 1
            elif inside and loc["rel_path"] in seen_rel and loc["status"] != "available":
                conn.execute("UPDATE locations SET status = 'available', last_seen_at = ? WHERE id = ?", (now, loc["id"]))
    on_progress(dict(stats))
    return stats


def _ingest_file(db: Database, source_id: str, root: Path, path: Path, rel_path: str, should_cancel) -> str:
    st = path.stat()
    size, mtime = st.st_size, st.st_mtime
    ext = path.suffix.lower()
    media_kind = media_kind_for(ext)
    now = now_iso()

    existing = db.one("SELECT * FROM locations WHERE source_id = ? AND rel_path = ?", (source_id, rel_path))
    if existing is not None and existing["size"] == size and abs(existing["mtime"] - mtime) < 1e-6:
        with db.tx() as conn:
            conn.execute("UPDATE locations SET status = 'available', last_seen_at = ? WHERE id = ?", (now, existing["id"]))
        _ensure_asset_and_jobs(db, existing["version_id"], rel_path, path.name, media_kind, ext)
        return "unchanged"

    digest = sha256_of(path, should_cancel=should_cancel)
    version = db.one("SELECT * FROM asset_versions WHERE sha256 = ?", (digest,))
    outcome = "unchanged"
    with db.tx() as conn:
        if version is None:
            version_id = new_id("ver")
            conn.execute(
                "INSERT INTO asset_versions(id, sha256, size, ext, media_kind, analysis_status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (version_id, digest, size, ext, media_kind, now),
            )
            outcome = "added"
        else:
            version_id = version["id"]
            outcome = "updated" if existing is not None else "unchanged"
        if existing is None:
            conn.execute(
                "INSERT INTO locations(id, version_id, source_id, rel_path, file_name, size, mtime, status, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?)",
                (new_id("loc"), version_id, source_id, rel_path, path.name, size, mtime, now),
            )
        else:
            conn.execute(
                "UPDATE locations SET version_id = ?, file_name = ?, size = ?, mtime = ?, status = 'available', last_seen_at = ? WHERE id = ?",
                (version_id, path.name, size, mtime, now, existing["id"]),
            )
    _ensure_asset_and_jobs(db, version_id, rel_path, path.name, media_kind, ext)
    return outcome


def _ensure_asset_and_jobs(db: Database, version_id: str, rel_path: str, file_name: str, media_kind: str, ext: str) -> None:
    now = now_iso()
    asset = db.one("SELECT id FROM assets WHERE version_id = ?", (version_id,))
    with db.tx() as conn:
        if asset is None:
            title = clean_title(file_name)
            category = infer_category(rel_path, media_kind, ext)
            conn.execute(
                "INSERT INTO assets(id, version_id, original_title, title, category, category_source, description, description_source, tags, favorite, search_text, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'inferred', '', 'none', '[]', 0, ?, ?, ?)",
                (new_id("ast"), version_id, file_name, title, category, build_search_text(title, file_name, "", [], rel_path), now, now),
            )
        version = conn.execute("SELECT analysis_status FROM asset_versions WHERE id = ?", (version_id,)).fetchone()
        pending_job = conn.execute(
            "SELECT id FROM jobs WHERE version_id = ? AND kind = 'analyze' AND status IN ('queued', 'running')", (version_id,)
        ).fetchone()
        if version["analysis_status"] in ("pending", "failed") and pending_job is None and media_kind != "other":
            conn.execute(
                "INSERT INTO jobs(id, kind, version_id, status, payload, created_at) VALUES (?, 'analyze', ?, 'queued', ?, ?)",
                (new_id("job"), version_id, json.dumps({"reason": "import"}), now),
            )
        if media_kind == "other" and version["analysis_status"] == "pending":
            conn.execute(
                "UPDATE asset_versions SET analysis_status = 'done', analysis = ?, analyzed_at = ? WHERE id = ?",
                (json.dumps({"media_kind": "other", "container": ext.lstrip("."), "preview_support": "none"}), now, version_id),
            )
