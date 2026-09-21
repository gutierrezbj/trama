"""API HTTP de TRAMA (FastAPI). Sirve también la interfaz compilada si existe."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .auth import COOKIE_NAME, PUBLIC_PATHS, LoginGuard, auth_status, is_authenticated, load_secret, sign_session, verify_password
from .backup import BackupError, list_backups, verify_backup
from .drive import DriveClient, DriveError, DriveNotConfigured, DriveNotConnected, build_auth_url, exchange_code, forget_token, load_token, new_pkce
from .config import ARCHIVE_EXT, CATEGORIES, LUT_EXT, REPO_ROOT, MEDIA_EXTENSIONS, REQUIRED_APP, Settings, source_id_for
from .db import Database, loads, new_id, normalize_text, now_iso
from .importer import build_search_text, ensure_source, resolve_subpath
from .media import MediaError, resolve_tools
from .packs import (
    DiskLimitError,
    PackError,
    cache_bytes_used,
    extract_entry,
    folder_tree,
    register_pack,
    release_entries,
    write_inventory_csv,
)
from .worker import (
    Worker,
    archived_pack_locations,
    enqueue_backup,
    enqueue_drive_upload,
    enqueue_extract,
    enqueue_import,
    enqueue_index_pack,
    enqueue_reanalyze,
    original_path_for_version,
)

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class AppState:
    def __init__(self, settings: Settings, db: Database, worker: Worker, drive_transport=None):
        self.settings = settings
        self.db = db
        self.worker = worker
        self.secret = load_secret(settings)
        self.guard = LoginGuard(db)
        self.drive_transport = drive_transport
        self.pkce: dict[str, str] = {}  # state → code_verifier (flujo OAuth en curso)


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
        "SELECT l.id, l.source_id, s.label AS source_label, l.rel_path, l.file_name, l.status, l.size, l.last_seen_at, l.kind, l.external_id, l.checksum, l.verified_at, "
        "e.pack_id, p.label AS pack_label, e.inner_path, e.status AS entry_status, e.error AS entry_error, e.unsafe_reason "
        "FROM locations l JOIN sources s ON s.id = l.source_id LEFT JOIN pack_entries e ON e.id = l.pack_entry_id LEFT JOIN packs p ON p.id = e.pack_id "
        "WHERE l.version_id = ? ORDER BY l.status = 'available' DESC, l.last_seen_at DESC",
        (version_id,),
    )]
    derivatives = {}
    for d in db.query("SELECT kind, status, error, width, height FROM derivatives WHERE version_id = ?", (version_id,)):
        derivatives[d["kind"]] = {"status": d["status"], "error": d["error"], "width": d["width"], "height": d["height"]}
    media_kind = row["media_kind"]
    summary = _summary(analysis, media_kind)
    alpha = bool(summary["alpha_format"]) and summary["alpha_used"] is not False and media_kind == "video"
    available = any(l["status"] == "available" and l["kind"] != "drive" for l in locations)
    remote_available = any(l["status"] == "available" and l["kind"] == "drive" for l in locations)
    archived = any(l["status"] == "archived" for l in locations)

    if media_kind == "video":
        kinds = ["proxy_dark", "proxy_light", "proxy_checker"] if alpha else ["proxy"]
        preview_kind = "video_alpha" if alpha else "video"
    elif media_kind == "audio":
        kinds, preview_kind = ["audio_proxy"], "audio"
    elif media_kind == "image":
        kinds, preview_kind = [], "image"
    elif analysis.get("preview_support") == "lut_demo" or row["ext"] in LUT_EXT:
        kinds, preview_kind = ["lut_demo"], "lut_demo"
    else:
        kinds, preview_kind = [], "none"

    if row["analysis_status"] == "failed":
        preview_status = "failed"
    elif row["analysis_status"] != "done":
        preview_status = "archived" if (archived and not available) else "pending"
    elif preview_kind == "none":
        preview_status = "unsupported"
    elif preview_kind == "image":
        preview_status = "ready" if available else "archived"
    else:
        statuses = [derivatives.get(k, {}).get("status", "pending") for k in kinds]
        preview_status = "ready" if statuses and all(s == "ready" for s in statuses) else ("failed" if "failed" in statuses else "pending")

    provider_preview = None
    if row.get("provider_preview_asset_id"):
        pp = db.one(
            "SELECT a.id, a.title, d.status FROM assets a JOIN derivatives d ON d.version_id = a.version_id AND d.kind = 'thumb' WHERE a.id = ?",
            (row["provider_preview_asset_id"],),
        )
        if pp:
            provider_preview = {"asset_id": pp["id"], "title": pp["title"], "thumb_url": f"/api/assets/{pp['id']}/thumb" if pp["status"] == "ready" else None}
        else:
            other = db.one("SELECT id, title FROM assets WHERE id = ?", (row["provider_preview_asset_id"],))
            if other:
                provider_preview = {"asset_id": other["id"], "title": other["title"], "thumb_url": None}

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
            "identity_kind": row.get("identity_kind") or "sha256",
            "size": row["size"],
            "ext": row["ext"],
            "media_kind": media_kind,
            "analysis_status": row["analysis_status"],
            "analysis_error": row["analysis_error"],
            "analyzed_at": row["analyzed_at"],
        },
        "summary": summary,
        "available": available,
        "remote_available": remote_available,
        "in_drive": remote_available,
        "archived": archived and not available,
        "extractable": archived and any(l["kind"] == "pack" and l["status"] == "archived" for l in locations),
        "duplicate_of": row.get("duplicate_of"),
        "required_app": REQUIRED_APP.get(row["ext"]) if media_kind == "other" else None,
        "provider_preview": provider_preview,
        "lut": analysis.get("lut"),
        "locations": locations,
        "derivatives": derivatives,
        "preview": {"kind": preview_kind, "status": preview_status, "backgrounds": ["dark", "light", "checker"] if alpha else []},
        "thumb_url": f"/api/assets/{asset_id}/thumb" if derivatives.get("thumb", {}).get("status") == "ready" else None,
        "lut_demo_url": f"/api/assets/{asset_id}/lut-demo" if derivatives.get("lut_demo", {}).get("status") == "ready" else None,
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
    "SELECT a.*, v.sha256, v.identity_kind, v.size, v.ext, v.media_kind, v.analysis_status, v.analysis_error, v.analysis, v.analyzed_at "
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


class PackIndexCreate(BaseModel):
    source_id: str
    path: str = ""   # un archivo .zip o una carpeta (todos sus .zip directos)


class PackPatch(BaseModel):
    label: str | None = None


class ExtractBody(BaseModel):
    prefix: str = ""
    entry_ids: list[str] = Field(default_factory=list)


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


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class BackupCreate(BaseModel):
    label: str = ""
    upload: bool = False


# ----------------------------------------------------------------- app

def create_app(settings: Settings, db: Database | None = None, start_worker: bool = True, drive_transport=None) -> FastAPI:
    settings.ensure_dirs()
    db = db or Database(settings.db_path)
    db.migrate()
    worker = Worker(db, settings)
    worker.drive_transport = drive_transport  # type: ignore[attr-defined]
    state = AppState(settings, db, worker, drive_transport)
    for root in settings.allowed_roots:
        if root.is_dir():
            ensure_source(db, root)

    app = FastAPI(title="TRAMA", version=__version__, docs_url="/api/docs" if settings.auth_mode == "off" else None, openapi_url="/api/openapi.json" if settings.auth_mode == "off" else None)
    app.state.trama = state

    @app.middleware("http")
    async def require_auth(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_PATHS:
            if not is_authenticated(state.settings, state.secret, request.cookies.get(COOKIE_NAME), request.headers.get("authorization")):
                return JSONResponse({"detail": "Inicia sesión para acceder a TRAMA"}, status_code=401, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "private, no-store")
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    # ---- acceso ---------------------------------------------------------------
    @app.get("/api/auth/status")
    def get_auth_status(request: Request):
        st_ = auth_status(state.settings)
        st_["authenticated"] = is_authenticated(state.settings, state.secret, request.cookies.get(COOKIE_NAME), request.headers.get("authorization"))
        return st_

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        if state.settings.auth_mode != "password":
            return {"ok": True, "mode": "off"}
        ip = request.client.host if request.client else "?"
        wait = state.guard.blocked_for(ip)
        if wait:
            raise HTTPException(429, f"Demasiados intentos; espera {wait} s")
        if not verify_password(body.password, state.settings.password_hash):
            failures = state.guard.register_failure(ip)
            raise HTTPException(401, f"Contraseña incorrecta ({failures} fallos)")
        state.guard.reset(ip)
        token = sign_session(state.secret, state.settings.session_hours)
        response.set_cookie(COOKIE_NAME, token, max_age=state.settings.session_hours * 3600, httponly=True, samesite="strict", secure=state.settings.cookie_secure, path="/")
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.on_event("startup")
    def _startup() -> None:
        if start_worker:
            worker.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        worker.stop()
        db.close()

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
            "auth": auth_status(st.settings),
            "drive": _drive_status(st, probe=False),
            "backups_dir": str(st.settings.backups_dir),
        }

    # ---- Google Drive ---------------------------------------------------------
    def _drive_status(st: AppState, probe: bool = True) -> dict:
        s = st.settings
        out: dict[str, Any] = {
            "configured": s.drive_configured,
            "connected": s.drive_configured and s.drive_token_file.is_file(),
            "folder_name": s.drive_folder_name,
            "scope": "drive.file (solo archivos creados por TRAMA)",
            "client_file": str(s.drive_client_file) if s.drive_client_file else None,
            "redirect_uri": None,
            "account": None,
            "folder_id": None,
            "error": None,
        }
        try:
            from .drive import redirect_uri

            out["redirect_uri"] = redirect_uri(s)
        except Exception:
            pass
        if out["connected"]:
            tok = load_token(s) or {}
            out["folder_id"] = tok.get("folder_id")
            out["files"] = st.db.one("SELECT COUNT(*) AS n FROM locations WHERE kind = 'drive' AND status = 'available'")["n"]
            if probe:
                client = None
                try:
                    client = DriveClient(s, st.drive_transport)
                    about = client.about()
                    out["account"] = about.get("user", {}).get("emailAddress")
                    quota = about.get("storageQuota", {})
                    out["quota"] = {"usage": int(quota.get("usage", 0)), "limit": int(quota["limit"]) if quota.get("limit") else None}
                    out["folder_id"] = client.ensure_folder()
                except DriveError as exc:
                    out["error"] = str(exc)
                finally:
                    if client:
                        client.close()
        return out

    @app.get("/api/drive/status")
    def drive_status(st: AppState = Depends(S)):
        return _drive_status(st)

    @app.post("/api/drive/auth/start")
    def drive_auth_start(st: AppState = Depends(S)):
        try:
            state_token, verifier = new_pkce()
            url = build_auth_url(st.settings, state_token, verifier)
        except DriveNotConfigured as exc:
            raise HTTPException(409, str(exc))
        st.pkce = {state_token: verifier}  # un solo flujo en curso
        return {"url": url}

    @app.get("/api/drive/auth/callback")
    def drive_auth_callback(state: str = "", code: str = "", error: str = "", st: AppState = Depends(S)):
        # Público (Google redirige aquí sin cookie), pero solo es útil con un state emitido por una sesión autenticada.
        if error:
            return RedirectResponse(f"/#/copias?drive_error={error}", status_code=303)
        verifier = st.pkce.pop(state, None)
        if not verifier:
            raise HTTPException(400, "Estado OAuth desconocido o caducado; inicia la conexión de nuevo")
        try:
            exchange_code(st.settings, code, verifier, st.drive_transport)
        except DriveError as exc:
            return RedirectResponse(f"/#/copias?drive_error={exc}", status_code=303)
        return RedirectResponse("/#/copias?drive=connected", status_code=303)

    @app.post("/api/drive/disconnect")
    def drive_disconnect(st: AppState = Depends(S)):
        forget_token(st.settings)
        return {"ok": True}

    @app.post("/api/assets/{asset_id}/drive-upload", status_code=202)
    def drive_upload_asset(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        _require_drive(st)
        if original_path_for_version(st.db, st.settings, row["version_id"]) is None:
            raise HTTPException(409, "El original no está disponible en este equipo; no se puede subir")
        job_id = enqueue_drive_upload(st.db, row["version_id"])
        st.worker.notify()
        return {"job_id": job_id, "message": None if job_id else "Ya estaba en Drive"}

    @app.post("/api/selections/{sid}/drive-upload", status_code=202)
    def drive_upload_selection(sid: str, st: AppState = Depends(S)):
        _named_get(st, "selections", sid)
        _require_drive(st)
        rows = st.db.query("SELECT a.version_id FROM selection_items si JOIN assets a ON a.id = si.asset_id WHERE si.selection_id = ?", (sid,))
        queued = skipped = 0
        for r in rows:
            if original_path_for_version(st.db, st.settings, r["version_id"]) is None:
                skipped += 1
                continue
            if enqueue_drive_upload(st.db, r["version_id"]):
                queued += 1
        st.worker.notify()
        return {"queued": queued, "skipped_offline": skipped}

    def _require_drive(st: AppState) -> None:
        if not st.settings.drive_configured:
            raise HTTPException(409, "Drive no configurado: falta client_secret.json")
        if not st.settings.drive_token_file.is_file():
            raise HTTPException(409, "Drive no conectado: autoriza el acceso desde «Copias y Drive»")

    @app.post("/api/assets/{asset_id}/drive-verify")
    def drive_verify_asset(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        _require_drive(st)
        loc = st.db.one("SELECT * FROM locations WHERE version_id = ? AND kind = 'drive'", (row["version_id"],))
        if loc is None:
            raise HTTPException(404, "Este recurso no está en Drive")
        client = DriveClient(st.settings, st.drive_transport)
        try:
            meta = client.get_file(loc["external_id"])
        finally:
            client.close()
        ok = bool(meta) and not meta.get("trashed") and int(meta.get("size", -1)) == loc["size"] and (not meta.get("md5Checksum") or meta["md5Checksum"] == loc["checksum"])
        with st.db.tx() as conn:
            conn.execute("UPDATE locations SET status = ?, verified_at = ? WHERE id = ?", ("available" if ok else "offline", now_iso(), loc["id"]))
        return {"ok": ok, "remote": meta}

    # ---- respaldos --------------------------------------------------------------
    @app.get("/api/backups")
    def get_backups(st: AppState = Depends(S)):
        job = st.db.one("SELECT id, status, progress, message, error FROM jobs WHERE kind = 'backup' ORDER BY created_at DESC LIMIT 1")
        return {"backups": list_backups(st.db), "dir": str(st.settings.backups_dir), "keep": st.settings.backup_keep, "last_job": dict(job) if job else None}

    @app.post("/api/backups", status_code=202)
    def create_backup_job(body: BackupCreate, st: AppState = Depends(S)):
        if body.upload:
            _require_drive(st)
        job_id = enqueue_backup(st.db, body.label.strip()[:40], body.upload)
        st.worker.notify()
        return {"job_id": job_id}

    @app.get("/api/backups/{backup_id}/verify")
    def verify_backup_api(backup_id: str, st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM backups WHERE id = ?", (backup_id,))
        if row is None:
            raise HTTPException(404, "Respaldo no encontrado")
        try:
            return {"ok": True, **verify_backup(Path(row["path"]))}
        except BackupError as exc:
            return {"ok": False, "error": str(exc)}

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
        dirs, zips, media_here = [], [], 0
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except PermissionError:
            raise HTTPException(403, "Sin permiso para leer la carpeta")
        known_packs = {r["rel_path"]: dict(r) for r in st.db.query("SELECT id, rel_path, status, entries_media FROM packs WHERE source_id = ?", (source_id,))}
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                count = zip_count = 0
                try:
                    with os.scandir(entry.path) as sub:
                        for e in sub:
                            if e.is_file():
                                ext = Path(e.name).suffix.lower()
                                count += ext in MEDIA_EXTENSIONS
                                zip_count += ext in ARCHIVE_EXT
                except OSError:
                    pass
                dirs.append({"name": entry.name, "path": f"{rel}/{entry.name}" if rel else entry.name, "media_files": count, "zip_files": zip_count})
            elif entry.is_file():
                ext = Path(entry.name).suffix.lower()
                if ext in MEDIA_EXTENSIONS:
                    media_here += 1
                elif ext in ARCHIVE_EXT:
                    zrel = f"{rel}/{entry.name}" if rel else entry.name
                    known = known_packs.get(zrel)
                    zips.append({"name": entry.name, "path": zrel, "size": entry.stat().st_size, "pack_id": known["id"] if known else None, "pack_status": known["status"] if known else None, "entries_media": known["entries_media"] if known else None})
        parent = None if not rel else ("/".join(rel.split("/")[:-1]))
        return {"source_id": source_id, "path": rel, "parent": parent, "dirs": dirs, "zips": zips, "media_files": media_here}

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

    # ---- packs (ZIP) -------------------------------------------------------
    def _pack_out(st: AppState, row: dict) -> dict:
        row = dict(row)
        agg = st.db.one(
            "SELECT COALESCE(SUM(CASE WHEN status = 'extracted' THEN 1 ELSE 0 END), 0) AS extracted, "
            "COALESCE(SUM(CASE WHEN status = 'extracted' THEN size ELSE 0 END), 0) AS extracted_bytes, "
            "COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed FROM pack_entries WHERE pack_id = ?",
            (row["id"],),
        )
        row.update({"extracted": agg["extracted"], "extracted_bytes": agg["extracted_bytes"], "failed": agg["failed"]})
        job = st.db.one(
            "SELECT id, kind, status, progress, message FROM jobs WHERE kind IN ('index_pack','extract') AND status IN ('queued','running') AND json_extract(payload, '$.pack_id') = ? ORDER BY created_at LIMIT 1",
            (row["id"],),
        )
        row["active_job"] = dict(job) if job else None
        root = st.settings.source_for_id(row["source_id"])
        row["zip_present"] = bool(root and (root / Path(*row["rel_path"].split("/"))).is_file())
        return row

    @app.get("/api/packs")
    def list_packs(st: AppState = Depends(S)):
        return [_pack_out(st, r) for r in st.db.query("SELECT * FROM packs ORDER BY label")]

    @app.post("/api/packs/index", status_code=202)
    def index_packs(body: PackIndexCreate, st: AppState = Depends(S)):
        root = st.settings.source_for_id(body.source_id)
        if root is None:
            raise HTTPException(404, "Fuente desconocida")
        if not root.is_dir():
            raise HTTPException(409, f"La raíz no está accesible: {root}")
        try:
            target = resolve_subpath(root, body.path)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if target.is_file() and target.suffix.lower() in ARCHIVE_EXT:
            zips = [target]
        elif target.is_dir():
            zips = sorted(p for p in target.iterdir() if p.is_file() and p.suffix.lower() in ARCHIVE_EXT)
        else:
            raise HTTPException(404, "No es un ZIP ni una carpeta")
        if not zips:
            raise HTTPException(404, "No hay archivos ZIP en esa carpeta")
        ensure_source(st.db, root)
        out = []
        for z in zips:
            rel = z.resolve().relative_to(root.resolve()).as_posix()
            pack = register_pack(st.db, body.source_id, rel, z)
            job_id = enqueue_index_pack(st.db, pack["id"])
            out.append({"pack_id": pack["id"], "label": pack["label"], "job_id": job_id})
        st.worker.notify()
        return {"packs": out}

    @app.get("/api/packs/{pack_id}")
    def get_pack(pack_id: str, depth: int = Query(3, ge=1, le=6), st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
        if row is None:
            raise HTTPException(404, "Pack no encontrado")
        out = _pack_out(st, dict(row))
        out["folders"] = folder_tree(st.db, pack_id, depth)
        out["unsafe_entries"] = [dict(r) for r in st.db.query("SELECT inner_path, unsafe_reason FROM pack_entries WHERE pack_id = ? AND status = 'unsafe' LIMIT 50", (pack_id,))]
        out["failed_entries"] = [dict(r) for r in st.db.query("SELECT id, inner_path, error FROM pack_entries WHERE pack_id = ? AND status = 'failed' LIMIT 50", (pack_id,))]
        return out

    @app.patch("/api/packs/{pack_id}")
    def patch_pack(pack_id: str, body: PackPatch, st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
        if row is None:
            raise HTTPException(404, "Pack no encontrado")
        if body.label is not None and body.label.strip():
            with st.db.tx() as conn:
                conn.execute("UPDATE packs SET label = ? WHERE id = ?", (body.label.strip(), pack_id))
        return _pack_out(st, dict(st.db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))))

    @app.post("/api/packs/{pack_id}/reindex", status_code=202)
    def reindex_pack(pack_id: str, st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
        if row is None:
            raise HTTPException(404, "Pack no encontrado")
        zip_path = st.settings.source_for_id(row["source_id"])
        if zip_path:
            zip_path = zip_path / Path(*row["rel_path"].split("/"))
            if zip_path.is_file():
                register_pack(st.db, row["source_id"], row["rel_path"], zip_path)
        job_id = enqueue_index_pack(st.db, pack_id)
        st.worker.notify()
        return {"job_id": job_id}

    @app.post("/api/packs/{pack_id}/extract", status_code=202)
    def extract_pack(pack_id: str, body: ExtractBody, st: AppState = Depends(S)):
        row = st.db.one("SELECT * FROM packs WHERE id = ?", (pack_id,))
        if row is None:
            raise HTTPException(404, "Pack no encontrado")
        if row["status"] != "indexed":
            raise HTTPException(409, "El pack no está indexado")
        from .packs import select_entries

        pending = select_entries(st.db, pack_id, body.prefix, body.entry_ids)
        total = sum(e["size"] for e in pending)
        if not pending:
            return {"job_id": None, "entries": 0, "bytes": 0, "message": "Nada pendiente de extraer en esa selección"}
        try:
            from .packs import check_disk_limits

            check_disk_limits(st.db, st.settings, total)
        except DiskLimitError as exc:
            raise HTTPException(507, str(exc))
        job_id = enqueue_extract(st.db, pack_id, body.prefix, body.entry_ids)
        st.worker.notify()
        return {"job_id": job_id, "entries": len(pending), "bytes": total}

    @app.post("/api/packs/{pack_id}/release")
    def release_pack(pack_id: str, body: ExtractBody, st: AppState = Depends(S)):
        if st.db.one("SELECT 1 FROM packs WHERE id = ?", (pack_id,)) is None:
            raise HTTPException(404, "Pack no encontrado")
        n = release_entries(st.db, st.settings, pack_id, body.prefix, body.entry_ids)
        return {"released": n}

    @app.get("/api/packs/{pack_id}/inventory.csv")
    def pack_inventory(pack_id: str, st: AppState = Depends(S)):
        try:
            path = write_inventory_csv(st.db, st.settings, pack_id)
        except PackError as exc:
            raise HTTPException(404, str(exc))
        label = st.db.one("SELECT label FROM packs WHERE id = ?", (pack_id,))["label"]
        return FileResponse(path, media_type="text/csv", filename=f"inventario-{label}.csv")

    @app.get("/api/storage")
    def storage(st: AppState = Depends(S)):
        import shutil as _sh

        usage = _sh.disk_usage(st.settings.data_dir)
        deriv = 0
        for p in st.settings.derivatives_dir.rglob("*"):
            if p.is_file():
                deriv += p.stat().st_size
        return {
            "data_dir": str(st.settings.data_dir),
            "cache_bytes": cache_bytes_used(st.db),
            "cache_max_bytes": st.settings.cache_max_bytes,
            "derivatives_bytes": deriv,
            "disk_free_bytes": usage.free,
            "disk_total_bytes": usage.total,
            "min_free_bytes": st.settings.min_free_bytes,
        }

    @app.get("/api/duplicates")
    def duplicates(st: AppState = Depends(S)):
        """Grupos de ubicaciones que comparten bytes: confirmados (SHA-256) y candidatos (crc32+tamaño)."""
        rows = st.db.query(
            "SELECT v.id AS version_id, v.identity_kind, v.size, COUNT(l.id) AS n, "
            "(SELECT a.id FROM assets a WHERE a.version_id = v.id ORDER BY a.created_at LIMIT 1) AS asset_id, "
            "(SELECT a.title FROM assets a WHERE a.version_id = v.id ORDER BY a.created_at LIMIT 1) AS title "
            "FROM asset_versions v JOIN locations l ON l.version_id = v.id GROUP BY v.id HAVING COUNT(l.id) > 1 ORDER BY v.size DESC"
        )
        out = []
        for r in rows:
            locs = st.db.query(
                "SELECT l.rel_path, l.status, l.kind, s.label AS source_label, p.label AS pack_label FROM locations l JOIN sources s ON s.id = l.source_id "
                "LEFT JOIN pack_entries e ON e.id = l.pack_entry_id LEFT JOIN packs p ON p.id = e.pack_id WHERE l.version_id = ?",
                (r["version_id"],),
            )
            out.append({**dict(r), "confirmed": r["identity_kind"] == "sha256", "locations": [dict(l) for l in locs]})
        linked = [dict(x) for x in st.db.query("SELECT id, title, duplicate_of FROM assets WHERE duplicate_of IS NOT NULL")]
        return {"groups": out, "linked_assets": linked}

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
        pack_id: str | None = None,
        media_kind: str | None = None,
        duplicates: bool | None = None,
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
        elif availability == "archived":
            where.append("NOT EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'available') AND EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'archived')")
        elif availability == "offline":
            where.append("NOT EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status IN ('available','archived'))")
        if pack_id:
            where.append("EXISTS (SELECT 1 FROM pack_entries e WHERE e.version_id = v.id AND e.pack_id = ?)")
            params.append(pack_id)
        if media_kind:
            kinds = [k for k in media_kind.split(",") if k]
            where.append("v.media_kind IN (" + ",".join("?" for _ in kinds) + ")")
            params += kinds
        if duplicates:
            where.append("(a.duplicate_of IS NOT NULL OR (SELECT COUNT(*) FROM locations l WHERE l.version_id = v.id) > 1)")
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
        pending = st.db.one("SELECT COUNT(*) AS n FROM asset_versions v WHERE v.analysis_status IN ('pending','running') AND EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'available')")["n"]
        failed = st.db.one("SELECT COUNT(*) AS n FROM asset_versions WHERE analysis_status = 'failed'")["n"]
        archived = st.db.one("SELECT COUNT(*) AS n FROM assets a JOIN asset_versions v ON v.id = a.version_id WHERE NOT EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'available') AND EXISTS (SELECT 1 FROM locations l WHERE l.version_id = v.id AND l.status = 'archived')")["n"]
        packs = st.db.one("SELECT COUNT(*) AS n FROM packs")["n"]
        return {"total": total, "favorites": fav, "categories": cats, "analysis_pending": pending, "analysis_failed": failed, "archived": archived, "packs": packs}

    @app.get("/api/tags")
    def tags(st: AppState = Depends(S)):
        counts: dict[str, int] = {}
        for r in st.db.query("SELECT tags FROM assets"):
            for t in loads(r["tags"], []):
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        original_path_for_version(st.db, st.settings, row["version_id"])  # refresca available/offline/archived contra el disco
        return serialize_asset(st, row, detail=True)

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
        if original_path_for_version(st.db, st.settings, row["version_id"]) is None:
            raise HTTPException(409, "El original no está disponible; extrae o reconecta la fuente antes de reanalizar")
        enqueue_reanalyze(st.db, row["version_id"])
        st.worker.notify()
        return serialize_asset(st, get_asset_row(st.db, asset_id), detail=True)

    @app.post("/api/assets/{asset_id}/extract", status_code=202)
    def extract_asset(asset_id: str, st: AppState = Depends(S)):
        """Extrae del pack (en segundo plano) la primera copia archivada de este recurso."""
        row = get_asset_row(st.db, asset_id)
        if original_path_for_version(st.db, st.settings, row["version_id"]) is not None:
            return {"job_id": None, "message": "Ya hay una copia disponible"}
        locs = archived_pack_locations(st.db, row["version_id"])
        if not locs:
            raise HTTPException(404, "No hay copia en ningún pack registrado")
        loc = locs[0]
        try:
            from .packs import check_disk_limits

            check_disk_limits(st.db, st.settings, loc["size"])
        except DiskLimitError as exc:
            raise HTTPException(507, str(exc))
        job_id = enqueue_extract(st.db, loc["pack_id"], "", [loc["entry_id"]])
        st.worker.notify()
        return {"job_id": job_id}

    @app.post("/api/assets/{asset_id}/release")
    def release_asset(asset_id: str, st: AppState = Depends(S)):
        """Libera las copias extraídas de este recurso (los derivados y la ficha se conservan)."""
        row = get_asset_row(st.db, asset_id)
        entries = st.db.query("SELECT id, pack_id FROM pack_entries WHERE version_id = ? AND status = 'extracted'", (row["version_id"],))
        n = 0
        for e in entries:
            n += release_entries(st.db, st.settings, e["pack_id"], "", [e["id"]])
        return {"released": n}

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

    @app.get("/api/assets/{asset_id}/lut-demo")
    def asset_lut_demo(asset_id: str, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        path = _derivative_path(st, row["version_id"], "lut_demo")
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

    def _stream_from_drive(st: AppState, loc: dict, request: Request, inline: bool):
        """El original solo está en Drive: se sirve en streaming con rangos, sin exponer enlaces de Drive."""
        try:
            client = DriveClient(st.settings, st.drive_transport)
        except DriveError as exc:
            raise HTTPException(409, f"Original solo en Drive y Drive no disponible: {exc}")
        try:
            status, headers, body = client.stream_file(loc["external_id"], request.headers.get("range"))
        except DriveError as exc:
            client.close()
            raise HTTPException(502, str(exc))
        from urllib.parse import quote

        disposition = "inline" if inline else "attachment"
        headers["Content-Disposition"] = f"{disposition}; filename*=utf-8''{quote(loc['file_name'])}"
        headers.setdefault("Accept-Ranges", "bytes")

        def gen():
            try:
                yield from body
            finally:
                client.close()

        return StreamingResponse(gen(), status_code=status, headers=headers, media_type=headers.get("content-type", "application/octet-stream"))

    @app.get("/api/assets/{asset_id}/original")
    def asset_original(asset_id: str, request: Request, inline: bool = False, st: AppState = Depends(S)):
        row = get_asset_row(st.db, asset_id)
        path = original_path_for_version(st.db, st.settings, row["version_id"])
        if path is None:
            # Copia solo dentro de un pack: extracción bajo demanda (síncrona, una entrada) y se sirve.
            locs = archived_pack_locations(st.db, row["version_id"])
            if not locs:
                drive_loc = st.db.one("SELECT * FROM locations WHERE version_id = ? AND kind = 'drive' AND status = 'available'", (row["version_id"],))
                if drive_loc is None:
                    raise HTTPException(404, "El original no puede obtenerse: la fuente está offline")
                return _stream_from_drive(st, drive_loc, request, inline)
            loc = locs[0]
            pack = dict(st.db.one("SELECT * FROM packs WHERE id = ?", (loc["pack_id"],)))
            entry = dict(st.db.one("SELECT * FROM pack_entries WHERE id = ?", (loc["entry_id"],)))
            try:
                extract_entry(st.db, st.settings, pack, entry, lambda: False)
            except DiskLimitError as exc:
                raise HTTPException(507, str(exc))
            except PackError as exc:
                raise HTTPException(409, f"No se pudo extraer del pack: {exc}")
            st.worker.notify()
            path = original_path_for_version(st.db, st.settings, row["version_id"])
            if path is None:
                raise HTTPException(500, "La extracción terminó pero el archivo no aparece en la caché")
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
            # index.html nunca se cachea: los bundles llevan hash y cambian con cada build.
            return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return JSONResponse({"detail": "Interfaz no compilada. Ejecuta `npm run build` en frontend/ o usa `npm run dev`."})

    return app
