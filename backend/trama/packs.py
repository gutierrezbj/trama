"""Packs ZIP: lectura segura del índice, catalogado provisional y extracción selectiva.

Reglas (docs/ARQUITECTURA.md):
- Rutas validadas contra traversal, absolutas y unidades; se rechazan enlaces simbólicos,
  profundidades y tamaños excesivos y relaciones de compresión sospechosas.
- Nunca se extrae todo de forma recursiva: solo lo pedido (entrada, carpeta o pack) y en una
  caché separada con control de espacio.
- Identidad provisional (crc32 + tamaño) hasta tener los bytes; SHA-256 completo antes de
  confirmar un duplicado. Los duplicados no se borran: se relacionan.
- Los errores de una entrada se registran sin perder el lote.
"""
from __future__ import annotations

import hashlib
import tempfile
import os
import posixpath
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable

from .config import ARCHIVE_EXT, LUT_EXT, MEDIA_EXTENSIONS, PREVIEWABLE_OTHER, Settings, media_kind_for
from .db import Database, new_id, now_iso
from .importer import ImportCancelled, build_search_text, clean_title, infer_category

CHUNK = 4 * 1024 * 1024


class PackError(RuntimeError):
    pass


class DiskLimitError(PackError):
    pass


@dataclass
class EntryInfo:
    inner_path: str
    file_name: str
    ext: str
    media_kind: str
    size: int
    compressed_size: int
    crc32: int
    unsafe_reason: str | None


# ------------------------------------------------------------------ seguridad

def decode_name(info: zipfile.ZipInfo) -> str:
    """Corrige nombres guardados sin la bandera UTF-8 (zipfile los decodifica como cp437)."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def classify_entry(info: zipfile.ZipInfo, settings: Settings) -> EntryInfo:
    raw = decode_name(info)
    norm = raw.replace("\\", "/")
    reason: str | None = None
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    mode = (info.external_attr >> 16) & 0xFFFF
    if norm.startswith("/") or PureWindowsPath(raw).drive or norm.startswith("//"):
        reason = "ruta absoluta o con unidad"
    elif any(p == ".." for p in parts):
        reason = "ruta con '..' (traversal)"
    elif len(parts) > settings.zip_max_depth:
        reason = f"más de {settings.zip_max_depth} niveles"
    elif mode and stat.S_ISLNK(mode):
        reason = "enlace simbólico"
    elif info.file_size > settings.zip_max_entry_bytes:
        reason = "tamaño declarado excesivo"
    elif info.compress_size > 0 and info.file_size / info.compress_size > settings.zip_max_ratio and info.file_size > 1024 * 1024:
        reason = "relación de compresión sospechosa"
    elif info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        reason = f"método de compresión no soportado ({info.compress_type})"
    inner = "/".join(parts)
    file_name = parts[-1] if parts else raw
    ext = Path(file_name).suffix.lower()
    if file_name.startswith("._") or any(p.lower() == "__macosx" for p in parts[:-1]):
        kind = "ignored"  # basura de macOS (AppleDouble), no es multimedia
    elif ext in ARCHIVE_EXT:
        kind = "ignored"  # el ZIP anidado no es un recurso; su contenido se cataloga aparte (un nivel)
    elif ext in MEDIA_EXTENSIONS:
        kind = media_kind_for(ext)
    else:
        kind = "ignored"
    return EntryInfo(inner, file_name, ext, kind, info.file_size, info.compress_size, info.CRC & 0xFFFFFFFF, reason)


# ZIP dentro del ZIP (p. ej. descargas de plantillas): se cataloga su contenido, un solo nivel.
# La ruta interna de esas entradas es «carpeta/plantilla.zip!/dentro/archivo.mov».
NESTED_SEP = "!/"
NESTED_MAX_BYTES = 4 * 1024**3


def _copy_member_to_temp(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    fd, path = tempfile.mkstemp(prefix="trama-anidado-", suffix=".zip")
    with os.fdopen(fd, "wb") as out, zf.open(info) as src:
        shutil.copyfileobj(src, out, CHUNK)
    return path


def read_nested_index(zf: zipfile.ZipFile, outer: EntryInfo, info: zipfile.ZipInfo, settings: Settings) -> list[EntryInfo]:
    """Entradas de un ZIP anidado, con las mismas comprobaciones de seguridad que el exterior."""
    if outer.unsafe_reason or outer.size > NESTED_MAX_BYTES:
        return []
    path = _copy_member_to_temp(zf, info)
    try:
        try:
            nz = zipfile.ZipFile(path)
        except zipfile.BadZipFile:
            return []
        with nz:
            out = []
            for i in nz.infolist():
                if i.is_dir() or decode_name(i).endswith("/"):
                    continue
                e = classify_entry(i, settings)
                if e.ext in ARCHIVE_EXT:
                    continue  # un solo nivel: ZIP dentro de ZIP dentro de ZIP no se abre
                e.inner_path = f"{outer.inner_path}{NESTED_SEP}{e.inner_path}"
                out.append(e)
            return out
    finally:
        os.unlink(path)


def read_index(zip_path, settings: Settings, nested: bool = True) -> list[EntryInfo]:
    """`zip_path` puede ser una ruta o un archivo con seek (p. ej. un ZIP en Drive por rangos)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise PackError(f"ZIP inválido: {exc}") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and not decode_name(i).endswith("/")]
        if len(infos) > settings.zip_max_entries:
            raise PackError(f"El ZIP tiene {len(infos)} entradas; el límite es {settings.zip_max_entries}")
        entries = []
        for i in infos:
            e = classify_entry(i, settings)
            entries.append(e)
            if nested and e.ext in ARCHIVE_EXT:
                entries.extend(read_nested_index(zf, e, i, settings))
        if len(entries) > settings.zip_max_entries:
            raise PackError(f"El ZIP tiene {len(entries)} entradas contando los anidados; el límite es {settings.zip_max_entries}")
        return entries


# ------------------------------------------------------------------ catálogo

def provisional_key(crc32: int, size: int) -> str:
    return f"prov:{crc32:08x}:{size}"


def pack_zip_path(settings: Settings, pack: dict) -> Path | None:
    root = settings.source_for_id(pack["source_id"])
    if root is None:
        return None
    return root / Path(*pack["rel_path"].split("/"))


def cache_path_for(settings: Settings, pack_id: str, inner_path: str) -> Path:
    return settings.cache_dir / pack_id / Path(*inner_path.split("/"))


def default_pack_label(zip_path: Path) -> str:
    """Etiqueta legible: quita el sufijo que añade Google Drive a las descargas divididas
    (`nombre-20260920T113322Z-1-007.zip` → `nombre (007)`). Editable después."""
    import re

    stem = zip_path.stem
    m = re.match(r"^(.*?)-\d{8}T\d{6}Z-\d+(?:-(\d+))?$", stem)
    if m:
        return f"{m.group(1)} ({m.group(2)})" if m.group(2) else m.group(1)
    return stem


def register_pack(db: Database, source_id: str, rel_path: str, zip_path: Path) -> dict:
    st = zip_path.stat()
    existing = db.one("SELECT * FROM packs WHERE source_id = ? AND rel_path = ?", (source_id, rel_path))
    now = now_iso()
    with db.tx() as conn:
        if existing is None:
            pack_id = new_id("pck")
            conn.execute(
                "INSERT INTO packs(id, source_id, rel_path, label, size, mtime, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (pack_id, source_id, rel_path, default_pack_label(zip_path), st.st_size, st.st_mtime, now),
            )
        else:
            pack_id = existing["id"]
            conn.execute("UPDATE packs SET size = ?, mtime = ?, status = CASE WHEN status = 'offline' THEN 'indexed' ELSE status END WHERE id = ?", (st.st_size, st.st_mtime, pack_id))
    return dict(db.one("SELECT * FROM packs WHERE id = ?", (pack_id,)))


def index_pack(db: Database, settings: Settings, pack_id: str, should_cancel: Callable[[], bool], on_progress: Callable[[float, str], None]) -> dict:
    pack = db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
    if pack is None:
        raise PackError("Pack inexistente")
    zip_path = pack_zip_path(settings, dict(pack))
    remote = None
    if zip_path is not None and zip_path.is_file():
        source = zip_path
    elif pack["drive_file_id"]:
        # Pack que solo está en Drive: se lee el directorio central por rangos, sin descargar el ZIP.
        from .drive import DriveClient, RemoteFile

        remote = RemoteFile(DriveClient(settings, getattr(settings, "_drive_transport", None)), pack["drive_file_id"], int(pack["size"]))
        source = remote
    else:
        with db.tx() as conn:
            conn.execute("UPDATE packs SET status = 'offline', error = 'El archivo ZIP no está accesible' WHERE id = ?", (pack_id,))
        raise PackError("El archivo ZIP no está accesible")
    with db.tx() as conn:
        conn.execute("UPDATE packs SET status = 'indexing', error = NULL WHERE id = ?", (pack_id,))
    on_progress(0.05, "Leyendo el índice del ZIP")
    try:
        entries = read_index(source, settings)
    finally:
        if remote is not None:
            remote.close()
    on_progress(0.3, f"Catalogando {len(entries)} entradas")
    stats = {"total": len(entries), "media": 0, "unsafe": 0, "bytes": 0, "new_assets": 0}
    now = now_iso()
    known = {r["inner_path"]: dict(r) for r in db.query("SELECT * FROM pack_entries WHERE pack_id = ?", (pack_id,))}
    with db.tx() as conn:
        for i, e in enumerate(entries):
            if should_cancel():
                raise ImportCancelled()
            stats["bytes"] += e.size
            status = "unsafe" if e.unsafe_reason else ("ignored" if e.media_kind == "ignored" else "archived")
            if e.unsafe_reason:
                stats["unsafe"] += 1
            row = known.get(e.inner_path)
            if row is None:
                entry_id = new_id("ent")
                conn.execute(
                    "INSERT INTO pack_entries(id, pack_id, inner_path, file_name, ext, media_kind, size, compressed_size, crc32, status, unsafe_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry_id, pack_id, e.inner_path, e.file_name, e.ext, e.media_kind, e.size, e.compressed_size, e.crc32, status, e.unsafe_reason),
                )
                row = {"id": entry_id, "version_id": None, "status": status, "size": e.size, "crc32": e.crc32}
            elif row["status"] in ("unsafe", "ignored") and status == "archived":
                conn.execute("UPDATE pack_entries SET status = 'archived', unsafe_reason = NULL WHERE id = ?", (row["id"],))
            if status != "archived" and row["status"] not in ("archived", "extracted", "failed"):
                continue
            stats["media"] += 1
            if row.get("version_id"):
                continue
            # Identidad provisional: misma crc32+tamaño → misma versión provisional (candidato a duplicado).
            key = provisional_key(e.crc32, e.size)
            version = conn.execute("SELECT id FROM asset_versions WHERE sha256 = ?", (key,)).fetchone()
            if version is None:
                version_id = new_id("ver")
                conn.execute(
                    "INSERT INTO asset_versions(id, sha256, size, ext, media_kind, analysis_status, identity_kind, created_at) VALUES (?, ?, ?, ?, ?, 'pending', 'provisional', ?)",
                    (version_id, key, e.size, e.ext, e.media_kind, now),
                )
            else:
                version_id = version["id"]
            conn.execute("UPDATE pack_entries SET version_id = ? WHERE id = ?", (version_id, row["id"]))
            loc_rel = f"{pack['rel_path']}!/{e.inner_path}"
            loc = conn.execute("SELECT id FROM locations WHERE source_id = ? AND rel_path = ?", (pack["source_id"], loc_rel)).fetchone()
            if loc is None:
                conn.execute(
                    "INSERT INTO locations(id, version_id, source_id, rel_path, file_name, size, mtime, status, last_seen_at, kind, pack_entry_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'archived', ?, 'pack', ?)",
                    (new_id("loc"), version_id, pack["source_id"], loc_rel, e.file_name, e.size, pack["mtime"], now, row["id"]),
                )
            asset = conn.execute("SELECT id FROM assets WHERE version_id = ?", (version_id,)).fetchone()
            if asset is None:
                title = clean_title(e.file_name)
                category = infer_category(e.inner_path, e.media_kind, e.ext)
                conn.execute(
                    "INSERT INTO assets(id, version_id, original_title, title, category, category_source, description, description_source, tags, favorite, search_text, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'inferred', '', 'none', '[]', 0, ?, ?, ?)",
                    (new_id("ast"), version_id, e.file_name, title, category, build_search_text(title, e.file_name, "", [], f"{pack['label']}/{e.inner_path}"), now, now),
                )
                stats["new_assets"] += 1
        conn.execute(
            "UPDATE packs SET status = 'indexed', entries_total = ?, entries_media = ?, entries_unsafe = ?, bytes_total = ?, indexed_at = ?, error = NULL WHERE id = ?",
            (stats["total"], stats["media"], stats["unsafe"], stats["bytes"], now_iso(), pack_id),
        )
    link_provider_previews(db, pack_id=pack_id)
    on_progress(1.0, f"{stats['media']} recursos, {stats['unsafe']} entradas rechazadas")
    return stats


def register_drive_packs(db: Database, files: list[dict], source_id: str) -> list[str]:
    """Da de alta como packs los ZIP de la carpeta TRAMA/Packs de Drive que el catálogo aún no
    conoce (ni por id de Drive ni por md5). Devuelve los ids de los packs nuevos."""
    known_ids = {r["drive_file_id"] for r in db.query("SELECT drive_file_id FROM packs WHERE drive_file_id IS NOT NULL")}
    known_md5 = {r["drive_md5"] for r in db.query("SELECT drive_md5 FROM packs WHERE drive_md5 IS NOT NULL")}
    new_ids: list[str] = []
    now = now_iso()
    with db.tx() as conn:
        for f in files:
            name = f.get("name") or ""
            if not name.lower().endswith(".zip") or f["id"] in known_ids or (f.get("md5Checksum") and f["md5Checksum"] in known_md5):
                continue
            if conn.execute("SELECT 1 FROM packs WHERE source_id = ? AND rel_path = ?", (source_id, name)).fetchone():
                continue
            pack_id = new_id("pck")
            conn.execute(
                "INSERT INTO packs(id, source_id, rel_path, label, size, mtime, status, created_at, drive_file_id, drive_md5, drive_verified_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 'pending', ?, ?, ?, ?)",
                (pack_id, source_id, name, default_pack_label(Path(name)), int(f.get("size") or 0), now, f["id"], f.get("md5Checksum"), now),
            )
            known_ids.add(f["id"])
            if f.get("md5Checksum"):
                known_md5.add(f["md5Checksum"])
            new_ids.append(pack_id)
    return new_ids


def link_provider_previews(db: Database, pack_id: str | None = None) -> int:
    """Para archivos sin preview genérica (plantillas, LUT…), enlaza un hermano con el mismo
    nombre base en la misma carpeta que sí sea vídeo o imagen: la preview del proveedor."""
    if pack_id:
        rows = db.query(
            "SELECT a.id AS asset_id, e.inner_path, e.media_kind FROM pack_entries e JOIN assets a ON a.version_id = e.version_id WHERE e.pack_id = ? AND e.media_kind IN ('other','video','image')",
            (pack_id,),
        )
    else:
        rows = db.query(
            "SELECT a.id AS asset_id, l.rel_path AS inner_path, v.media_kind FROM locations l JOIN asset_versions v ON v.id = l.version_id JOIN assets a ON a.version_id = v.id WHERE l.kind = 'local' AND v.media_kind IN ('other','video','image')"
        )
    by_stem: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        p = posixpath.normpath(r["inner_path"])
        key = (posixpath.dirname(p), Path(posixpath.basename(p)).stem.lower())
        by_stem.setdefault(key, []).append(dict(r))
    linked = 0
    with db.tx() as conn:
        for group in by_stem.values():
            others = [g for g in group if g["media_kind"] == "other"]
            previews = [g for g in group if g["media_kind"] in ("video", "image")]
            if not others or not previews:
                continue
            preview = sorted(previews, key=lambda g: g["media_kind"] != "video")[0]
            for o in others:
                conn.execute("UPDATE assets SET provider_preview_asset_id = ? WHERE id = ? AND provider_preview_asset_id IS NULL", (preview["asset_id"], o["asset_id"]))
                linked += 1
    return linked


# ------------------------------------------------------------------ extracción

def cache_bytes_used(db: Database) -> int:
    row = db.one("SELECT COALESCE(SUM(size), 0) AS n FROM pack_entries WHERE status = 'extracted'")
    return int(row["n"]) if row else 0


def reconcile_cache(db: Database, settings: Settings) -> int:
    """Entradas marcadas como extraídas cuya copia ya no está en la caché (p. ej. tras restaurar el
    catálogo en otra máquina) vuelven a «dentro del pack», para no contar espacio fantasma."""
    fixed = 0
    rows = db.query("SELECT id, pack_id, inner_path FROM pack_entries WHERE status = 'extracted'")
    with db.tx() as conn:
        for r in rows:
            if not cache_path_for(settings, r["pack_id"], r["inner_path"]).is_file():
                conn.execute("UPDATE pack_entries SET status = 'archived', extracted_at = NULL WHERE id = ?", (r["id"],))
                conn.execute("UPDATE locations SET status = 'archived' WHERE pack_entry_id = ?", (r["id"],))
                fixed += 1
    return fixed


def check_disk_limits(db: Database, settings: Settings, incoming: int) -> None:
    used = cache_bytes_used(db)
    if used + incoming > settings.cache_max_bytes:
        raise DiskLimitError(
            f"Límite de caché alcanzado: {used / 1024**3:.1f} GB usados de {settings.cache_max_bytes / 1024**3:.0f} GB. Libera copias extraídas o sube TRAMA_CACHE_MAX_GB."
        )
    free = shutil.disk_usage(settings.data_dir).free
    if free - incoming < settings.min_free_bytes:
        raise DiskLimitError(
            f"Espacio libre insuficiente: quedarían {(free - incoming) / 1024**3:.1f} GB y el mínimo es {settings.min_free_bytes / 1024**3:.0f} GB."
        )


def select_entries(db: Database, pack_id: str, prefix: str = "", entry_ids: Iterable[str] | None = None) -> list[dict]:
    if entry_ids:
        ids = list(entry_ids)
        rows = db.query(
            f"SELECT * FROM pack_entries WHERE pack_id = ? AND id IN ({','.join('?' for _ in ids)})", [pack_id, *ids]
        )
    else:
        rows = db.query("SELECT * FROM pack_entries WHERE pack_id = ? ORDER BY inner_path", (pack_id,))
        if prefix:
            p = prefix.strip("/")
            rows = [r for r in rows if r["inner_path"] == p or r["inner_path"].startswith(p + "/")]
    return [dict(r) for r in rows if r["status"] in ("archived", "failed")]


def extract_entry(db: Database, settings: Settings, pack: dict, entry: dict, should_cancel: Callable[[], bool], on_bytes: Callable[[int], None] | None = None, zf: zipfile.ZipFile | None = None) -> str:
    """Extrae una entrada a la caché, calcula SHA-256 y concilia la identidad. Devuelve el version_id final."""
    zip_path = pack_zip_path(settings, pack)
    local_ok = zip_path is not None and zip_path.is_file()
    if zf is None and not local_ok and not pack.get("drive_file_id"):
        raise PackError("El ZIP no está accesible ni en este equipo ni en Drive")
    if entry["status"] == "unsafe":
        raise PackError(f"Entrada rechazada: {entry['unsafe_reason']}")
    check_disk_limits(db, settings, entry["size"])
    dest = cache_path_for(settings, pack["id"], entry["inner_path"])
    # La ruta de destino debe quedar dentro de la caché del pack (segunda barrera).
    base = (settings.cache_dir / pack["id"]).resolve()
    if base not in dest.resolve().parents:
        raise PackError("Destino fuera de la caché")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    written = 0
    remote = None
    if zf is not None:
        source = zf  # ZIP ya abierto por el llamador (lotes): no se relee el directorio central
    elif local_ok:
        source = zip_path
    else:
        # ZIP solo en Drive: lectura aleatoria por rangos HTTP; solo viajan el índice y esta entrada.
        from .drive import DriveClient, RemoteFile

        client = DriveClient(settings, getattr(settings, "_drive_transport", None))
        remote = RemoteFile(client, pack["drive_file_id"], int(pack["size"]))
        source = remote
    try:
        _extract_from(source, entry, tmp, digest, should_cancel, on_bytes)
    finally:
        if remote is not None:
            remote.close()
    written = tmp.stat().st_size if tmp.exists() else 0
    if written != entry["size"]:
        tmp.unlink(missing_ok=True)
        raise PackError(f"Tamaño extraído ({written}) distinto del declarado ({entry['size']})")
    tmp.replace(dest)
    sha = digest.hexdigest()
    return reconcile_identity(db, entry, sha, written)


def _extract_from(source, entry: dict, tmp: Path, digest, should_cancel, on_bytes) -> None:
    if isinstance(source, zipfile.ZipFile):
        _extract_member(source, entry, tmp, digest, should_cancel, on_bytes)
        return
    with zipfile.ZipFile(source) as zf:
        try:
            _extract_member(zf, entry, tmp, digest, should_cancel, on_bytes)
        finally:
            close_nested(zf)


def _find(zf: zipfile.ZipFile, inner: str) -> zipfile.ZipInfo | None:
    return next((i for i in zf.infolist() if decode_name(i).replace("\\", "/").strip("/") == inner), None)


def _nested_zip(zf: zipfile.ZipFile, outer: str) -> zipfile.ZipFile:
    """ZIP anidado abierto desde una copia temporal; se guarda en el ZIP exterior para que un lote
    de entradas del mismo anidado no lo vuelva a sacar. Se borra con `close_nested`."""
    cache = zf.__dict__.setdefault("_trama_nested", {})
    if outer not in cache:
        info = _find(zf, outer)
        if info is None:
            raise PackError("El ZIP anidado ya no está en el pack")
        for old in list(cache):  # uno abierto cada vez: los lotes van ordenados por ruta
            close_nested(zf, old)
        path = _copy_member_to_temp(zf, info)
        cache[outer] = (path, zipfile.ZipFile(path))
    return cache[outer][1]


def close_nested(zf: zipfile.ZipFile, only: str | None = None) -> None:
    cache = zf.__dict__.get("_trama_nested", {})
    for outer in [only] if only else list(cache):
        item = cache.pop(outer, None)
        if item:
            item[1].close()
            Path(item[0]).unlink(missing_ok=True)


def _extract_member(zf: zipfile.ZipFile, entry: dict, tmp: Path, digest, should_cancel, on_bytes) -> None:
    written = 0
    inner = entry["inner_path"]
    if NESTED_SEP in inner:
        outer, inner = inner.split(NESTED_SEP, 1)
        zf = _nested_zip(zf, outer)
    info = _find(zf, inner)
    if info is None:
        raise PackError("La entrada ya no está en el ZIP")
    with zf.open(info) as src, open(tmp, "wb") as out:
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > entry["size"]:
                raise PackError("La entrada excede su tamaño declarado (posible zip bomb)")
            out.write(chunk)
            digest.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
            if should_cancel():
                raise ImportCancelled()


class PackReader:
    """Abre el ZIP de un pack una sola vez (local si está, si no en Drive por rangos) para extraer
    muchas entradas seguidas sin volver a leer el directorio central en cada una."""

    def __init__(self, settings: Settings, pack: dict):
        self._remote = None
        zip_path = pack_zip_path(settings, pack)
        if zip_path is not None and zip_path.is_file():
            self.zf = zipfile.ZipFile(zip_path)
        elif pack.get("drive_file_id"):
            from .drive import DriveClient, RemoteFile

            client = DriveClient(settings, getattr(settings, "_drive_transport", None))
            self._remote = RemoteFile(client, pack["drive_file_id"], int(pack["size"]))
            self.zf = zipfile.ZipFile(self._remote)
        else:
            raise PackError("El ZIP no está accesible ni en este equipo ni en Drive")

    def __enter__(self) -> "PackReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        close_nested(self.zf)
        self.zf.close()
        if self._remote is not None:
            self._remote.close()


def reconcile_identity(db: Database, entry: dict, sha: str, size: int) -> str:
    """Convierte la identidad provisional en definitiva o la une a una versión existente.
    Duplicado confirmado por hash: las fichas sin ediciones se retiran; las editadas o usadas se
    conservan enlazadas con `duplicate_of`. Nunca se borran archivos."""
    now = now_iso()
    provisional_id = entry["version_id"]
    existing = db.one("SELECT * FROM asset_versions WHERE sha256 = ?", (sha,))
    with db.tx() as conn:
        if existing is None:
            if provisional_id:
                conn.execute("UPDATE asset_versions SET sha256 = ?, identity_kind = 'sha256', size = ? WHERE id = ?", (sha, size, provisional_id))
                final_id = provisional_id
            else:
                final_id = new_id("ver")
                conn.execute(
                    "INSERT INTO asset_versions(id, sha256, size, ext, media_kind, analysis_status, identity_kind, created_at) VALUES (?, ?, ?, ?, ?, 'pending', 'sha256', ?)",
                    (final_id, sha, size, entry["ext"], entry["media_kind"], now),
                )
        elif existing["id"] == provisional_id:
            final_id = provisional_id
        else:
            final_id = existing["id"]
            if provisional_id:
                conn.execute("UPDATE locations SET version_id = ? WHERE version_id = ?", (final_id, provisional_id))
                conn.execute("UPDATE pack_entries SET version_id = ? WHERE version_id = ?", (final_id, provisional_id))
                conn.execute("UPDATE derivatives SET version_id = ? WHERE version_id = ? AND kind NOT IN (SELECT kind FROM derivatives WHERE version_id = ?)", (final_id, provisional_id, final_id))
                conn.execute("DELETE FROM derivatives WHERE version_id = ?", (provisional_id,))
                conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE version_id = ? AND status = 'queued'", (now, provisional_id))
                keeper = conn.execute("SELECT id FROM assets WHERE version_id = ? ORDER BY created_at LIMIT 1", (final_id,)).fetchone()
                for a in conn.execute("SELECT * FROM assets WHERE version_id = ?", (provisional_id,)).fetchall():
                    edited = a["category_source"] == "human" or a["description_source"] == "human" or a["tags"] not in ("[]", "") or a["favorite"] or a["title_source"] == "human"
                    used = conn.execute("SELECT 1 FROM selection_items WHERE asset_id = ? UNION SELECT 1 FROM collection_assets WHERE asset_id = ?", (a["id"], a["id"])).fetchone()
                    if keeper is None:
                        conn.execute("UPDATE assets SET version_id = ? WHERE id = ?", (final_id, a["id"]))
                        keeper = a
                    elif edited or used:
                        conn.execute("UPDATE assets SET version_id = ?, duplicate_of = ? WHERE id = ?", (final_id, keeper["id"], a["id"]))
                    else:
                        conn.execute("UPDATE assets SET provider_preview_asset_id = ? WHERE provider_preview_asset_id = ?", (keeper["id"], a["id"]))
                        conn.execute("DELETE FROM assets WHERE id = ?", (a["id"],))
                conn.execute("DELETE FROM jobs WHERE version_id = ? AND status IN ('cancelled','done','failed')", (provisional_id,))
                conn.execute("DELETE FROM asset_versions WHERE id = ?", (provisional_id,))
        conn.execute("UPDATE pack_entries SET status = 'extracted', error = NULL, version_id = ?, extracted_at = ? WHERE id = ?", (final_id, now, entry["id"]))
        conn.execute("UPDATE locations SET status = 'available', last_seen_at = ?, version_id = ? WHERE pack_entry_id = ?", (now, final_id, entry["id"]))
        version = conn.execute("SELECT analysis_status, media_kind, ext FROM asset_versions WHERE id = ?", (final_id,)).fetchone()
        pending_job = conn.execute("SELECT id FROM jobs WHERE version_id = ? AND kind = 'analyze' AND status IN ('queued','running')", (final_id,)).fetchone()
        needs_analysis = version["media_kind"] != "other" or version["ext"] in PREVIEWABLE_OTHER
        if version["analysis_status"] in ("pending", "failed") and pending_job is None and needs_analysis:
            conn.execute(
                "INSERT INTO jobs(id, kind, version_id, status, payload, created_at) VALUES (?, 'analyze', ?, 'queued', '{\"reason\": \"extract\"}', ?)",
                (new_id("job"), final_id, now),
            )
        elif version["analysis_status"] == "pending" and not needs_analysis:
            conn.execute("UPDATE asset_versions SET analysis_status = 'done', analysis = ?, analyzed_at = ? WHERE id = ?", ('{"media_kind": "other", "preview_support": "none"}', now, final_id))
    return final_id


def release_entries(db: Database, settings: Settings, pack_id: str, prefix: str = "", entry_ids: Iterable[str] | None = None) -> int:
    """Borra copias extraídas de la caché (nunca el ZIP ni los derivados) y devuelve cuántas."""
    if entry_ids:
        ids = list(entry_ids)
        rows = db.query(f"SELECT * FROM pack_entries WHERE pack_id = ? AND status = 'extracted' AND id IN ({','.join('?' for _ in ids)})", [pack_id, *ids])
    else:
        rows = db.query("SELECT * FROM pack_entries WHERE pack_id = ? AND status = 'extracted'", (pack_id,))
        if prefix:
            p = prefix.strip("/")
            rows = [r for r in rows if r["inner_path"] == p or r["inner_path"].startswith(p + "/")]
    released = 0
    with db.tx() as conn:
        for r in rows:
            path = cache_path_for(settings, pack_id, r["inner_path"])
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            conn.execute("UPDATE pack_entries SET status = 'archived', extracted_at = NULL WHERE id = ?", (r["id"],))
            conn.execute("UPDATE locations SET status = 'archived' WHERE pack_entry_id = ?", (r["id"],))
            released += 1
    # Limpia carpetas vacías de la caché del pack.
    base = settings.cache_dir / pack_id
    if base.exists():
        for dirpath, dirnames, filenames in os.walk(base, topdown=False):
            if not dirnames and not filenames and Path(dirpath) != base:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass
    return released


def folder_tree(db: Database, pack_id: str, depth: int = 3) -> list[dict]:
    """Carpetas del pack con recuentos (para elegir qué extraer)."""
    rows = db.query("SELECT inner_path, size, status, media_kind FROM pack_entries WHERE pack_id = ?", (pack_id,))
    agg: dict[str, dict] = {}
    for r in rows:
        parts = r["inner_path"].split("/")[:-1]
        for d in range(0, min(depth, len(parts)) + 1):
            key = "/".join(parts[:d])
            node = agg.setdefault(key, {"path": key, "depth": d, "entries": 0, "media": 0, "extracted": 0, "bytes": 0, "extracted_bytes": 0, "unsafe": 0})
            node["entries"] += 1
            node["bytes"] += r["size"]
            if r["status"] in ("archived", "extracted", "failed"):
                node["media"] += 1
            if r["status"] == "extracted":
                node["extracted"] += 1
                node["extracted_bytes"] += r["size"]
            if r["status"] == "unsafe":
                node["unsafe"] += 1
    return sorted(agg.values(), key=lambda n: n["path"])


def write_inventory_csv(db: Database, settings: Settings, pack_id: str) -> Path:
    """Inventario privado en el directorio de datos (fuera del repositorio)."""
    import csv

    pack = db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
    if pack is None:
        raise PackError("Pack inexistente")
    path = settings.inventories_dir / f"{pack_id}.csv"
    rows = db.query(
        "SELECT e.inner_path, e.file_name, e.ext, e.media_kind, e.size, e.crc32, e.status, e.unsafe_reason, v.sha256, v.identity_kind, a.id AS asset_id, a.title, a.category "
        "FROM pack_entries e LEFT JOIN asset_versions v ON v.id = e.version_id LEFT JOIN assets a ON a.version_id = v.id WHERE e.pack_id = ? ORDER BY e.inner_path",
        (pack_id,),
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pack", "inner_path", "file_name", "ext", "media_kind", "size", "crc32", "status", "unsafe_reason", "sha256_or_provisional", "identity_kind", "asset_id", "title", "category"])
        for r in rows:
            w.writerow([pack["label"], r["inner_path"], r["file_name"], r["ext"], r["media_kind"], r["size"], f"{r['crc32']:08x}", r["status"], r["unsafe_reason"] or "", r["sha256"] or "", r["identity_kind"] or "", r["asset_id"] or "", r["title"] or "", r["category"] or ""])
    return path
