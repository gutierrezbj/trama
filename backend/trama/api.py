"""API HTTP de TRAMA (FastAPI). Sirve también la interfaz compilada si existe."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import CATEGORIES, REPO_ROOT, MEDIA_EXTENSIONS, Settings, source_id_for
from .db import Database, loads, new_id, normalize_text, now_iso
from .importer import build_search_text, ensure_source, resolve_subpath
from .media import MediaError, resolve_tools
from .worker import Worker, enqueue_import, enqueue_reanalyze, original_path_for_version

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class AppState:
    def __init__(self, settings: Settings, db: Database, worker: Worker):
        self.settings = settings
        self.db = db
        self.worker = worker


# ----------------------------------------------------------------- serialización

def _summary(analysis: dict, media_kind: str) -> dict:
    video = analysis.get("video") or {}
    audio = analysis.get("audio") or {}
    image = analysis.get("image") or {}
    return {
        "duration_s": analysis.get("duration_s"),
        "width": video.get("width") or image.get("width"),
        "height": video.get("height") or image.get("height"),
        "fps": video.get("fps"),
        "frames": video.get("frames"),
        "rotation": video.get("rotation"),
        "orientation": analysis.get("orientation"),
        "alpha_format": video.get("alpha_format") if video else image.get("alpha_format"),
        "alpha_used": video.get("alpha_used") if video else image.get("alpha_used"),
        "codec": video.get("codec") or audio.get("codec"),
        "pix_fmt": video.get("pix_fmt"),
        "container": analysis.get("container"),
        "has_audio": bool(audio),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
        "bits": audio.get("bits"),
        "media_kind": media_kind,
    }


def serialize_asset(state: AppState, row: dict, detail: bool = False) -> dict:
    db = state.db
    version_id = row["version_id"]
    analysis = loads(row.get("analysis"), {})
    locations = [dict(r) for r in db.query(
        "SELECT l.id, l.source_id, s.label AS source_label, l.rel_path, l.file_name, l.status, l.size, l.last_seen_at FROM locations l JOIN sources s ON s.id = l.source_id WHERE l.version_id = ? ORDER BY l.last_seen_at DESC",
        (version_id,),
    )]
    derivatives = {}
    for d in db.query("SELECT kind, status, error, width, height FROM derivatives WHERE version_id = ?", (version_id,)):
        derivatives[d["kind"]] = {"status": d["status"], "error": d["error"], "width": d["width"], "height": d["height"]}
    media_kind = row["media_kind"]
    summary = _summary(analysis, media_kind)
    alpha = bool(summary["alpha_format"]) and summary["alpha_used"] is not False and media_kind == "video"

    if media_kind == "video":
        kinds = ["proxy_dark", "proxy_light", "proxy_checker"] if alpha else ["proxy"]
        preview_kind = "video_alpha" if alpha else "video"
    elif media_kind == "audio":
        kinds, preview_kind = ["audio_proxy"], "audio"
    elif media_kind == "image":
        kinds, preview_kind = [], "image"
    else:
        kinds, preview_kind = [], "none"

    if row["analysis_status"] == "failed":
        preview_status = "failed"
    elif row["analysis_status"] != "done":
        preview_status = "pending"
    elif preview_kind == "none":
        preview_status = "unsupported"
    elif preview_kind == "image":
        preview_status = "ready"
    else:
        statuses = [derivatives.get(k, {}).get("status", "pending") for k in kinds]
        preview_status = "ready" if statuses and all(s == "ready" for s in statuses) else ("failed" if "failed" in statuses else "pending")

    asset_id = row["id"]
    data = {
        "id": asset_id,
        "title": row["title"],
        "original_title": row["original_title"],
        "category": row["category"],
        "category_source": row["category_source"],
        "description": row["description"],
        "description_source": row["description_source"],
        "tags": loads(row["tags"], []),
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": {
            "id": version_id,
            "sha256": row["sha256"],
            "size": row["size"],
            "ext": row["ext"],
            "media_kind": media_kind,
            "analysis_status": row["analysis_status"],
            "analysis_error": row["analysis_error"],
            "analyzed_at": row["analyzed_at"],
        },
        "summary": summary,
        "available": any(l["status"] == "available" for l in locations),
        "locations": locations,
        "derivatives": derivatives,
        "preview": {"kind": preview_kind, "status": preview_status, "backgrounds": ["dark", "light", "checker"] if alpha else []},
        "thumb_url": f"/api/assets/{asset_id}/thumb" if derivatives.get("thumb", {}).get("status") == "ready" else None,
        "waveform_url": f"/api/assets/{asset_id}/waveform" if derivatives.get("waveform", {}).get("status") == "ready" else None,
        "in_selections": [r["selection_id"] for r in db.query("SELECT selection_id FROM selection_items WHERE asset_id = ?", (asset_id,))],
        "in_collections": [r["collection_id"] for r in db.query("SELECT collection_id FROM collection_assets WHERE asset_id = ?", (asset_id,))],
    }
    if detail:
        data["analysis"] = analysis
        data["jobs"] = [dict(j) for j in db.query(
            "SELECT id, kind, status, attempts, progress, message, error, created_at, finished_at FROM jobs WHERE version_id = ? ORDER BY created_at DESC LIMIT 10", (version_id,)
        )]
    return data


ASSET_SELECT = (
    "SELECT a.*, v.sha256, v.size, v.ext, v.media_kind, v.analysis_status, v.analysis_error, v.analysis, v.analyzed_at "
    "FROM assets a JOIN asset_versions v ON v.id = a.version_id"
)


def get_asset_row(db: Database, asset_id: str) -> dict:
    row = db.one(ASSET_SELECT + " WHERE a.id = ?", (asset_id,))
    if row is None:
        raise HTTPException(404, "Recurso no encontrado")
    return dict(row)


# ----------------------------------------------------------------- modelos

class AssetPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    category: str | None = None
    favorite: bool | None = None


class ImportCreate(BaseModel):
    source_id: str
    path: str = ""


class NamedCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    notes: str = ""


class NamedPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    notes: str | None = None


class ItemPatch(BaseModel):
    note: str | None = None


class OrderBody(BaseModel):
    asset_ids: list[str]


# ----------------------------------------------------------------- app

def create_app(settings: Settings, db: Database | None = None, start_worker: bool = True) -> FastAPI:
    settings.ensure_dirs()
    db = db or Database(settings.db_path)
    db.migrate()
    worker = Worker(db, settings)
    state = AppState(settings, db, worker)
    for root in settings.allowed_roots:
        if root.is_dir():
            ensure_source(db, root)

    app = FastAPI(title="TRAMA", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.trama = state

    @app.on_event("startup")
    def _startup() -> None:
        if start_worker:
            worker.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        worker.stop()

    def S() -> AppState:
        return state

    # ---- configuración / fuentes ----------------------------------------
    @app.get("/api/config")
    def get_config(st: AppState = Depends(S)):
        tools: dict[str, Any]
        try:
            t = resolve_tools(st.settings)
            tools = {"ffmpeg": t.ffmpeg_version, "ffprobe": t.ffprobe_version, "ok": True}
        except MediaError as exc:
            tools = {"ok": False, "error": str(exc)}
        return {
            "version": __version__,
            "data_dir": str(st.settings.data_dir),
            "categories": CATEGORIES,
            "media_extensions": sorted(MEDIA_EXTENSIONS),
            "tools": tools,
            "sources": _sources(st),
        }

    def _sources(st: AppState) -> list[dict]:
        out = []
        for root in st.settings.allowed_roots:
            sid = source_id_for(root)
            n = st.db.one("SELECT COUNT(*) AS n FROM locations WHERE source_id = ?", (sid,))
            out.append({"id": sid, "label": root.name or str(root), "path": str(root), "exists": root.is_dir(), "locations": n["n"] if n else 0})
        return out

    @app.get("/api/fs/sources")
    def fs_sources(st: AppState = Depends(S)):
        return _sources(st)

    @app.get("/api/fs/browse")
    def fs_browse(source_id: str, path: str = "", st: AppState = Depends(S)):
        root = st.settings.source_for_id(source_id)
        if root is None:
            raise HTTPException(404, "Fuente desconocida")
        if not root.is_dir():
            raise HTTPException(409, f"La raíz no está accesible: {root}")
        try:
            folder = resolve_subpath(root, path)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not folder.is_dir():
            raise HTTPException(404, "Carpeta no encontrada")
        rel = folder.resolve().relative_to(root.resolve()).as_posix()
        rel = "" if rel == "." else rel
        dirs, media_here = [], 0
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except PermissionError:
            raise HTTPException(403, "Sin permiso para leer la carpeta")
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                count = 0
                try:
                    with os.scandir(entry.path) as sub:
                        count = sum(1 for e in sub if e.is_file() and Path(e.name).suffix.lower() in MEDIA_EXTENSIONS)
                except OSError:
                    pass
                dirs.append({"name": entry.name, "path": f"{rel}/{entry.name}" if rel else entry.name, "media_files": count})
            elif entry.is_file() and Path(entry.name).suffix.lower() in MEDIA_EXTENSIONS:
                media_here += 1
        parent = None if not rel else ("/".join(rel.split("/")[:-1]))
        return {"source_id": source_id, "path": rel, "parent": parent, "dirs": dirs, "media_files": media_here}

    # ---- importaciones y trabajos ----------------------------------------
    @app.post("/api/imports", status_code=201)
    def create_import(body: ImportCreate, st: AppState = Depends(S)):
        root = st.settings.source_for_id(body.source_id)
        if root is None:
            raise HTTPException(404, "Fuente desconocida")
        if not root.is_dir():
            raise HTTPException(409, f"La raíz no está accesible: {root}")
        try:
            folder = resolve_subpath(root, body.path)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not folder.is_dir():
            raise HTTPException(404, "Carpeta no encontrada")
        ensure_source(st.db, root)
        rel = folder.resolve().relative_to(root.resolve()).as_posix()
        imp = enqueue_import(st.db, body.source_id, "" if rel == "." else rel)
        st.worker.notify()
        return _import_out(imp)

    def _import_out(row: dict) -> dict:
        row = dict(row)
        row["errors"] = loads(row["errors"], [])
        return row

    @app.get("/api/imports")
    def list_imports(limit: int = 20, st: AppState = Depends(S)):
        return [_import_out(dict(r)) for r in st.db.query("SELECT * FROM imports ORDER BY created_at DESC LIMIT ?", (limit,))]

    @app.get("/api/imports/{import_id}")
    def get_import(import_id: str, st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM imports WHERE id = ?", (import_id,))
        if row is None:
            raise HTTPException(404, "Importación no encontrada")
        return _import_out(dict(row))

    @app.post("/api/imports/{import_id}/cancel")
    def cancel_import(import_id: str, st: AppState = Depends(S)):
        job = st.db.one("SELECT id FROM jobs WHERE import_id = ? ORDER BY created_at DESC LIMIT 1", (import_id,))
        if job is None:
            raise HTTPException(404, "Importación no encontrada")
        st.worker.cancel(job["id"])
        return {"ok": True}

    @app.get("/api/jobs/summary")
    def jobs_summary(st: AppState = Depends(S)):
        rows = st.db.query("SELECT kind, status, COUNT(*) AS n FROM jobs GROUP BY kind, status")
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["status"], {})[r["kind"]] = r["n"]
        totals = {status: sum(v.values()) for status, v in out.items()}
        return {"by_status": out, "totals": totals}

    @app.get("/api/jobs")
    def list_jobs(status: str | None = None, limit: int = 100, st: AppState = Depends(S)):
        sql = (
            "SELECT j.*, a.id AS asset_id, a.title AS asset_title FROM jobs j "
            "LEFT JOIN assets a ON a.version_id = j.version_id"
        )
        params: list = []
        if status:
            sql += " WHERE j.status IN (" + ",".join("?" for _ in status.split(",")) + ")"
            params += status.split(",")
        sql += " ORDER BY CASE j.status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'failed' THEN 2 ELSE 3 END, j.created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in st.db.query(sql, params)]

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: str, st: AppState = Depends(S)):
        if not st.worker.retry(job_id):
            raise HTTPException(409, "Solo se reintentan trabajos fallidos o cancelados")
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, st: AppState = Depends(S)):
        if not st.worker.cancel(job_id):
            raise HTTPException(404, "Trabajo no encontrado")
        return {"ok": True}

    @app.post("/api/jobs/retry-failed")
    def retry_failed(st: AppState = Depends(S)):
        ids = [r["id"] for r in st.db.query("SELECT id FROM jobs WHERE status = 'failed'")]
        for i in ids:
            st.worker.retry(i)
        return {"retried": len(ids)}

    # ---- recursos ----------------------------------------------------------
    @app.get("/api/assets")
    def list_assets(
        q: str = "",
        category: str | None = None,
        alpha: bool | None = None,
        orientation: str | None = None,
        max_duration: float | None = None,
        min_duration: float | None = None,
        availability: str | None = None,
        favorite: bool | None = None,
        analysis: str | None = None,
        collection_id: str | None = None,
        selection_id: str | None = None,
        sort: str = "recent",
        limit: int = Query(60, ge=1, le=500),
        offset: int = Query(0, ge=0),
        st: AppState = Depends(S),
    ):
        where, params = [], []
        for term in normalize_text(q).split():
            where.append("a.search_text LIKE ?")
            params.append(f"%{term}%")
        if category:
            cats = [c for c in category.split(",") if c]
            where.append("a.category IN (" + ",".join("?" for _ in cats) + ")")
            params += cats
        if alpha is True:
            where.append("COALESCE(json_extract(v.analysis,'$.video.alpha_format'), json_extract(v.analysis,'$.image.alpha_format')) = 1 AND COALESCE(json_extract(v.analysis,'$.video.alpha_used'), json_extract(v.analysis,'$.image.alpha_used'), 1) = 1")
        elif alpha is False:
            where.append("COALESCE(json_extract(v.analysis,'$.video.alpha_format'), json_extract(v.analysis,'$.image.alpha_format')) = 0")
        if orientation:
            where.append("json_extract(v.analysis,'$.orientation') = ?")
            params.append(orientation)
        if max_duration is not None:
            where.append("json_extract(v.analysis,'$.duration_s') <= ?")
            params.append(max_duration)
        if min_duration is not None:
            where.append("json_extract(v.analysis,'$.duration_s') >= ?")
            params.append(min_duration)
        if availability == "available":
            where.append("EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'available')")
        elif availability == "offline":
            where.append("NOT EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'available')")
        if favorite is not None:
            where.append("a.favorite = ?")
            params.append(1 if favorite else 0)
        if analysis:
            where.append("v.analysis_status = ?")
            params.append(analysis)
        if collection_id:
            where.append("EXISTS (SELECT 1 FROM collection_assets ca WHERE ca.asset_id = a.id AND ca.collection_id = ?)")
            params.append(collection_id)
        if selection_id:
            where.append("EXISTS (SELECT 1 FROM selection_items si WHERE si.asset_id = a.id AND si.selection_id = ?)")
            params.append(selection_id)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = {
            "recent": "a.created_at DESC, a.title",
            "title": "a.title COLLATE NOCASE",
            "duration": "json_extract(v.analysis,'$.duration_s') IS NULL, json_extract(v.analysis,'$.duration_s')",
            "size": "v.size DESC",
        }.get(sort, "a.created_at DESC")
        if selection_id:
            order = "(SELECT position FROM selection_items si WHERE si.asset_id = a.id AND si.selection_id = '" + selection_id.replace("'", "") + "')"
        total = st.db.one(f"SELECT COUNT(*) AS n FROM assets a JOIN asset_versions v ON v.id = a.version_id{clause}", params)["n"]
        rows = st.db.query(f"{ASSET_SELECT}{clause} ORDER BY {order} LIMIT ? OFFSET ?", params + [limit, offset])
        return {"items": [serialize_asset(st, dict(r)) for r in rows], "total": total, "limit": limit, "offset": offset}

    @app.get("/api/stats")
    def stats(st: AppState = Depends(S)):
        cats = {r["category"]: r["n"] for r in st.db.query("SELECT category, COUNT(*) AS n FROM assets GROUP BY category")}
        fav = st.db.one("SELECT COUNT(*) AS n FROM assets WHERE favorite = 1")["n"]
        total = st.db.one("SELECT COUNT(*) AS n FROM assets")["n"]
        pending = st.db.one("SELECT COUNT(*) AS n FROM asset_versions WHERE analysis_status IN ('pending','running')")["n"]
        failed = st.db.one("SELECT COUNT(*) AS n FROM asset_versions WHERE analysis_status = 'failed'")["n"]
        return {"total": total, "favorites": fav, "categories": cats, "analysis_pending": pending, "analysis_failed": failed}

    @app.get("/api/tags")
    def tags(st: AppState = Depends(S)):
        counts: dict[str, int] = {}
        for r in st.db.query("SELECT tags FROM assets"):
            for t in loads(r["tags"], []):
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str, st: AppState = Depends(S)):
        return serialize_asset(st, get_asset_row(st.db, asset_id), detail=True)

    @app.patch("/api/assets/{asset_id}")
    def patch_asset(asset_id: str, body: AssetPatch, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        title = body.title.strip() if body.title is not None else row["title"]
        if not title:
            raise HTTPException(400, "El título no puede quedar vacío")
        description = body.description.strip() if body.description is not None else row["description"]
        tags = loads(row["tags"], [])
        if body.tags is not None:
            seen, tags = set(), []
            for t in body.tags:
                t = t.strip()
                key = normalize_text(t)
                if t and key not in seen:
                    seen.add(key)
                    tags.append(t)
        category = row["category"]
        category_source = row["category_source"]
        if body.category is not None:
            if body.category not in CATEGORIES:
                raise HTTPException(400, f"Categoría desconocida: {body.category}")
            category, category_source = body.category, "human"
        description_source = row["description_source"]
        if body.description is not None:
            description_source = "human" if description else "none"
        favorite = int(body.favorite) if body.favorite is not None else row["favorite"]
        loc = st.db.one("SELECT rel_path FROM locations WHERE version_id = ? ORDER BY last_seen_at DESC LIMIT 1", (row["version_id"],))
        search = build_search_text(title, row["original_title"], description, tags, loc["rel_path"] if loc else "")
        with st.db.tx() as conn:
            conn.execute(
                "UPDATE assets SET title = ?, description = ?, description_source = ?, tags = ?, category = ?, category_source = ?, favorite = ?, search_text = ?, updated_at = ? WHERE id = ?",
                (title, description, description_source, json.dumps(tags, ensure_ascii=False), category, category_source, favorite, search, now_iso(), asset_id),
            )
        return serialize_asset(st, get_asset_row(st.db, asset_id), detail=True)

    @app.post("/api/assets/{asset_id}/reanalyze")
    def reanalyze(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        enqueue_reanalyze(st.db, row["version_id"])
        st.worker.notify()
        return serialize_asset(st, get_asset_row(st.db, asset_id), detail=True)

    # ---- archivos: siempre resueltos por ID, nunca por ruta del cliente ----
    def _derivative_path(st: AppState, version_id: str, kind: str) -> Path:
        d = st.db.one("SELECT * FROM derivatives WHERE version_id = ? AND kind = ?", (version_id, kind))
        if d is None or d["status"] != "ready" or not d["rel_path"]:
            status = d["status"] if d else "pending"
            raise HTTPException(404, f"Derivado {kind} no disponible ({status})")
        path = st.settings.derivatives_dir / d["rel_path"]
        if not path.is_file():
            raise HTTPException(404, "El derivado falta en disco; vuelve a analizar")
        return path

    @app.get("/api/assets/{asset_id}/thumb")
    def asset_thumb(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        path = _derivative_path(st, row["version_id"], "thumb")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/assets/{asset_id}/waveform")
    def asset_waveform(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        path = _derivative_path(st, row["version_id"], "waveform")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/assets/{asset_id}/preview")
    def asset_preview(asset_id: str, bg: str = "dark", st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        kind = row["media_kind"]
        if kind == "image":
            path = original_path_for_version(st.db, st.settings, row["version_id"])
            if path is None:
                raise HTTPException(404, "Original no accesible (fuente offline)")
            return FileResponse(path)
        if kind == "audio":
            return FileResponse(_derivative_path(st, row["version_id"], "audio_proxy"), media_type="audio/mp4")
        if kind == "video":
            has_alpha = st.db.one("SELECT 1 FROM derivatives WHERE version_id = ? AND kind = 'proxy_dark'", (row["version_id"],))
            if has_alpha:
                if bg not in ("dark", "light", "checker"):
                    raise HTTPException(400, "Fondo desconocido")
                return FileResponse(_derivative_path(st, row["version_id"], f"proxy_{bg}"), media_type="video/mp4")
            return FileResponse(_derivative_path(st, row["version_id"], "proxy"), media_type="video/mp4")
        raise HTTPException(404, "Este tipo de archivo no tiene preview")

    @app.get("/api/assets/{asset_id}/original")
    def asset_original(asset_id: str, inline: bool = False, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        path = original_path_for_version(st.db, st.settings, row["version_id"])
        if path is None:
            raise HTTPException(404, "El original no puede obtenerse: la fuente está offline")
        filename = st.db.one("SELECT file_name FROM locations WHERE version_id = ? ORDER BY last_seen_at DESC LIMIT 1", (row["version_id"],))["file_name"]
        return FileResponse(path, filename=filename, content_disposition_type="inline" if inline else "attachment")

    # ---- colecciones ------------------------------------------------------
    def _named_list(st: AppState, table: str, link: str, key: str) -> list[dict]:
        rows = st.db.query(
            f"SELECT t.*, (SELECT COUNT(*) FROM {link} x WHERE x.{key} = t.id) AS count, "
            f"(SELECT x.asset_id FROM {link} x WHERE x.{key} = t.id ORDER BY x.position, x.added_at LIMIT 1) AS cover_asset_id "
            f"FROM {table} t ORDER BY t.updated_at DESC"
        )
        return [dict(r) for r in rows]

    def _named_get(st: AppState, table: str, item_id: str) -> dict:
        row = st.db.one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))
        if row is None:
            raise HTTPException(404, "No encontrado")
        return dict(row)

    @app.get("/api/collections")
    def list_collections(st: AppState = Depends(S)):
        return _named_list(st, "collections", "collection_assets", "collection_id")

    @app.post("/api/collections", status_code=201)
    def create_collection(body: NamedCreate, st: AppState = Depends(S)):
        cid, now = new_id("col"), now_iso()
        with st.db.tx() as conn:
            conn.execute("INSERT INTO collections(id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (cid, body.name.strip(), body.description, now, now))
        return _named_get(st, "collections", cid)

    @app.get("/api/collections/{cid}")
    def get_collection(cid: str, st: AppState = Depends(S)):
        col = _named_get(st, "collections", cid)
        rows = st.db.query(ASSET_SELECT + " JOIN collection_assets ca ON ca.asset_id = a.id WHERE ca.collection_id = ? ORDER BY ca.position, ca.added_at", (cid,))
        col["assets"] = [serialize_asset(st, dict(r)) for r in rows]
        return col

    @app.patch("/api/collections/{cid}")
    def patch_collection(cid: str, body: NamedPatch, st: AppState = Depends(S)):
        col = _named_get(st, "collections", cid)
        with st.db.tx() as conn:
            conn.execute("UPDATE collections SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                         ((body.name or col["name"]).strip() or col["name"], body.description if body.description is not None else col["description"], now_iso(), cid))
        return _named_get(st, "collections", cid)

    @app.delete("/api/collections/{cid}")
    def delete_collection(cid: str, st: AppState = Depends(S)):
        _named_get(st, "collections", cid)
        with st.db.tx() as conn:
            conn.execute("DELETE FROM collections WHERE id = ?", (cid,))
        return {"ok": True}

    @app.put("/api/collections/{cid}/assets/{asset_id}")
    def add_to_collection(cid: str, asset_id: str, st: AppState = Depends(S)):
        _named_get(st, "collections", cid)
        get_asset_row(st.db, asset_id)
        with st.db.tx() as conn:
            pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM collection_assets WHERE collection_id = ?", (cid,)).fetchone()["p"]
            conn.execute("INSERT OR IGNORE INTO collection_assets(collection_id, asset_id, position, added_at) VALUES (?, ?, ?, ?)", (cid, asset_id, pos, now_iso()))
            conn.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (now_iso(), cid))
        return {"ok": True}

    @app.delete("/api/collections/{cid}/assets/{asset_id}")
    def remove_from_collection(cid: str, asset_id: str, st: AppState = Depends(S)):
        with st.db.tx() as conn:
            conn.execute("DELETE FROM collection_assets WHERE collection_id = ? AND asset_id = ?", (cid, asset_id))
            conn.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (now_iso(), cid))
        return {"ok": True}

    # ---- selecciones ------------------------------------------------------
    @app.get("/api/selections")
    def list_selections(st: AppState = Depends(S)):
        return _named_list(st, "selections", "selection_items", "selection_id")

    @app.post("/api/selections", status_code=201)
    def create_selection(body: NamedCreate, st: AppState = Depends(S)):
        sid, now = new_id("sel"), now_iso()
        with st.db.tx() as conn:
            conn.execute("INSERT INTO selections(id, name, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (sid, body.name.strip(), body.notes, now, now))
        return _named_get(st, "selections", sid)

    @app.get("/api/selections/{sid}")
    def get_selection(sid: str, st: AppState = Depends(S)):
        sel = _named_get(st, "selections", sid)
        rows = st.db.query(ASSET_SELECT + " JOIN selection_items si ON si.asset_id = a.id WHERE si.selection_id = ? ORDER BY si.position, si.added_at", (sid,))
        notes = {r["asset_id"]: r["note"] for r in st.db.query("SELECT asset_id, note FROM selection_items WHERE selection_id = ?", (sid,))}
        items = []
        for r in rows:
            a = serialize_asset(st, dict(r))
            a["item_note"] = notes.get(a["id"], "")
            items.append(a)
        sel["items"] = items
        return sel

    @app.patch("/api/selections/{sid}")
    def patch_selection(sid: str, body: NamedPatch, st: AppState = Depends(S)):
        sel = _named_get(st, "selections", sid)
        with st.db.tx() as conn:
            conn.execute("UPDATE selections SET name = ?, notes = ?, updated_at = ? WHERE id = ?",
                         ((body.name or sel["name"]).strip() or sel["name"], body.notes if body.notes is not None else sel["notes"], now_iso(), sid))
        return _named_get(st, "selections", sid)

    @app.delete("/api/selections/{sid}")
    def delete_selection(sid: str, st: AppState = Depends(S)):
        _named_get(st, "selections", sid)
        with st.db.tx() as conn:
            conn.execute("DELETE FROM selections WHERE id = ?", (sid,))
        return {"ok": True}

    @app.put("/api/selections/{sid}/items/{asset_id}")
    def add_to_selection(sid: str, asset_id: str, st: AppState = Depends(S)):
        _named_get(st, "selections", sid)
        get_asset_row(st.db, asset_id)
        with st.db.tx() as conn:
            pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM selection_items WHERE selection_id = ?", (sid,)).fetchone()["p"]
            conn.execute("INSERT OR IGNORE INTO selection_items(selection_id, asset_id, position, note, added_at) VALUES (?, ?, ?, '', ?)", (sid, asset_id, pos, now_iso()))
            conn.execute("UPDATE selections SET updated_at = ? WHERE id = ?", (now_iso(), sid))
        return {"ok": True}

    @app.patch("/api/selections/{sid}/items/{asset_id}")
    def patch_selection_item(sid: str, asset_id: str, body: ItemPatch, st: AppState = Depends(S)):
        with st.db.tx() as conn:
            conn.execute("UPDATE selection_items SET note = COALESCE(?, note) WHERE selection_id = ? AND asset_id = ?", (body.note, sid, asset_id))
        return {"ok": True}

    @app.delete("/api/selections/{sid}/items/{asset_id}")
    def remove_from_selection(sid: str, asset_id: str, st: AppState = Depends(S)):
        with st.db.tx() as conn:
            conn.execute("DELETE FROM selection_items WHERE selection_id = ? AND asset_id = ?", (sid, asset_id))
            conn.execute("UPDATE selections SET updated_at = ? WHERE id = ?", (now_iso(), sid))
        return {"ok": True}

    @app.put("/api/selections/{sid}/order")
    def order_selection(sid: str, body: OrderBody, st: AppState = Depends(S)):
        _named_get(st, "selections", sid)
        with st.db.tx() as conn:
            for pos, aid in enumerate(body.asset_ids):
                conn.execute("UPDATE selection_items SET position = ? WHERE selection_id = ? AND asset_id = ?", (pos, sid, aid))
            conn.execute("UPDATE selections SET updated_at = ? WHERE id = ?", (now_iso(), sid))
        return {"ok": True}

    # ---- interfaz compilada --------------------------------------------------
    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="static-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str, request: Request):
            if full_path.startswith("api/"):
                raise HTTPException(404, "Ruta de API desconocida")
            candidate = (FRONTEND_DIST / full_path).resolve()
            if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"detail": "Interfaz no compilada. Ejecuta `npm run build` en frontend/ o usa `npm run dev`."})

    return app
