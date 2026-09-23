"""Worker multimedia: cola persistente en SQLite, hilos con límite de concurrencia,
cancelación y reintentos. Vive dentro del mismo proceso que la API en E1."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from pathlib import Path

from .config import Settings
from .db import Database, loads, new_id, now_iso
from .importer import ImportCancelled, run_import
from .media import (
    RECIPES,
    MediaError,
    derivative_filename,
    derivative_mime,
    generate_derivative,
    plan_derivatives,
    probe_file,
    resolve_tools,
)

log = logging.getLogger("trama.worker")

JOB_PRIORITY = {"import": 0, "analyze": 1, "derive": 2}


class JobCancelled(Exception):
    pass


def original_path_for_version(db: Database, settings: Settings, version_id: str) -> Path | None:
    """Primera ubicación disponible cuyo archivo existe realmente. Marca offline/archived las que no.
    Ubicaciones de pack: el archivo es la copia extraída en la caché; si no está, sigue 'archived'."""
    from .packs import cache_path_for

    rows = db.query(
        "SELECT l.id, l.rel_path, l.status, l.source_id, l.kind, l.pack_entry_id, e.pack_id, e.inner_path, e.status AS entry_status "
        "FROM locations l LEFT JOIN pack_entries e ON e.id = l.pack_entry_id WHERE l.version_id = ? ORDER BY l.status = 'available' DESC, l.kind = 'local' DESC, l.last_seen_at DESC",
        (version_id,),
    )
    for row in rows:
        if row["kind"] == "drive":
            continue  # remoto: se sirve en streaming desde Drive (api.asset_original), nunca es ruta local
        if row["kind"] == "pack":
            if not row["pack_id"]:
                continue
            candidate = cache_path_for(settings, row["pack_id"], row["inner_path"])
            if candidate.is_file() and row["entry_status"] == "extracted":
                if row["status"] != "available":
                    with db.tx() as conn:
                        conn.execute("UPDATE locations SET status = 'available', last_seen_at = ? WHERE id = ?", (now_iso(), row["id"]))
                return candidate
            if row["status"] == "available":
                with db.tx() as conn:
                    conn.execute("UPDATE locations SET status = 'archived' WHERE id = ?", (row["id"],))
                    conn.execute("UPDATE pack_entries SET status = 'archived', extracted_at = NULL WHERE id = ? AND status = 'extracted'", (row["pack_entry_id"],))
            continue
        root = settings.source_for_id(row["source_id"])
        if root is None:
            continue
        candidate = root / Path(*row["rel_path"].split("/"))
        if candidate.is_file():
            if row["status"] != "available":
                with db.tx() as conn:
                    conn.execute("UPDATE locations SET status = 'available', last_seen_at = ? WHERE id = ?", (now_iso(), row["id"]))
            return candidate
        if row["status"] != "offline":
            with db.tx() as conn:
                conn.execute("UPDATE locations SET status = 'offline' WHERE id = ?", (row["id"],))
    return None


def archived_pack_locations(db: Database, version_id: str) -> list[dict]:
    """Ubicaciones dentro de un pack (no extraídas) cuyo ZIP sigue registrado."""
    return [dict(r) for r in db.query(
        "SELECT e.id AS entry_id, e.pack_id, e.inner_path, e.size, e.status, p.status AS pack_status FROM locations l "
        "JOIN pack_entries e ON e.id = l.pack_entry_id JOIN packs p ON p.id = e.pack_id WHERE l.version_id = ? AND l.kind = 'pack' AND e.status IN ('archived','failed')",
        (version_id,),
    )]


class Worker:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._procs: dict[str, object] = {}
        self._procs_lock = threading.Lock()
        self._wake = threading.Event()

    # ---- ciclo de vida ---------------------------------------------------
    def start(self) -> None:
        self.recover()
        for i in range(self.settings.workers):
            t = threading.Thread(target=self._loop, name=f"trama-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._procs_lock:
            for proc in list(self._procs.values()):
                try:
                    proc.kill()  # type: ignore[attr-defined]
                except Exception:
                    pass
        for t in self._threads:
            t.join(timeout=5)

    def notify(self) -> None:
        self._wake.set()

    def recover(self) -> None:
        """Tras un arranque, lo que quedó 'running' vuelve a la cola (no se pierde trabajo)."""
        with self.db.tx() as conn:
            conn.execute("UPDATE jobs SET status = 'queued', message = 'Reanudado tras reinicio' WHERE status = 'running'")
            conn.execute("UPDATE imports SET status = 'queued' WHERE status = 'running'")
            conn.execute("UPDATE asset_versions SET analysis_status = 'pending' WHERE analysis_status = 'running'")

    # ---- cola ------------------------------------------------------------
    def claim(self) -> dict | None:
        with self.db.tx() as conn:
            running = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) AS n FROM jobs WHERE status = 'running' GROUP BY kind")}
            limits = {"extract": self.settings.extract_concurrency, "index_pack": 1, "import": 1, "drive_upload": 1, "backup": 1, "pack_upload": 1}
            blocked = [k for k, lim in limits.items() if running.get(k, 0) >= lim]
            exclude = f" AND kind NOT IN ({','.join('?' for _ in blocked)})" if blocked else ""
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued'" + exclude +
                " ORDER BY CASE kind WHEN 'import' THEN 0 WHEN 'index_pack' THEN 0 WHEN 'analyze' THEN 1 WHEN 'derive' THEN 2 ELSE 3 END, created_at LIMIT 1",
                blocked,
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = ?, error = NULL, message = NULL, progress = 0 WHERE id = ?",
                (now_iso(), row["id"]),
            )
            return dict(row)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = None
            try:
                job = self.claim()
            except Exception:
                log.exception("No se pudo reclamar trabajo")
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._run(job)

    def _run(self, job: dict) -> None:
        job_id = job["id"]
        try:
            if job["kind"] == "import":
                self._run_import(job)
            elif job["kind"] == "analyze":
                self._run_analyze(job)
            elif job["kind"] == "derive":
                self._run_derive(job)
            elif job["kind"] == "index_pack":
                self._run_index_pack(job)
            elif job["kind"] == "extract":
                self._run_extract(job)
            elif job["kind"] == "drive_upload":
                self._run_drive_upload(job)
            elif job["kind"] == "pack_upload":
                self._run_pack_upload(job)
            elif job["kind"] == "backup":
                self._run_backup(job)
            else:
                raise RuntimeError(f"Tipo de trabajo desconocido: {job['kind']}")
            self._finish(job_id, "done")
        except (JobCancelled, ImportCancelled):
            self._finish(job_id, "cancelled", error="Cancelado")
        except Exception as exc:
            log.error("Trabajo %s falló: %s\n%s", job_id, exc, traceback.format_exc())
            self._finish(job_id, "failed", error=str(exc) or exc.__class__.__name__)

    def _finish(self, job_id: str, status: str, error: str | None = None) -> None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ?, progress = CASE WHEN ? = 'done' THEN 1 ELSE progress END WHERE id = ?",
                (status, error, now_iso(), status, job_id),
            )

    def _progress(self, job_id: str, progress: float, message: str | None = None) -> None:
        with self.db.tx() as conn:
            conn.execute("UPDATE jobs SET progress = ?, message = COALESCE(?, message) WHERE id = ?", (progress, message, job_id))

    def _cancel_requested(self, job_id: str) -> bool:
        row = self.db.one("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))
        return bool(row and row["cancel_requested"])

    def _register(self, job_id: str):
        def register(proc):
            with self._procs_lock:
                if proc is None:
                    self._procs.pop(job_id, None)
                else:
                    self._procs[job_id] = proc
        return register

    def cancel(self, job_id: str) -> bool:
        row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            return False
        with self.db.tx() as conn:
            if row["status"] == "queued":
                conn.execute("UPDATE jobs SET status = 'cancelled', error = 'Cancelado antes de empezar', finished_at = ? WHERE id = ?", (now_iso(), job_id))
            else:
                conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
            if row["import_id"]:
                conn.execute("UPDATE imports SET cancel_requested = 1 WHERE id = ?", (row["import_id"],))
        with self._procs_lock:
            proc = self._procs.get(job_id)
        if proc is not None:
            try:
                proc.kill()  # type: ignore[attr-defined]
            except Exception:
                pass
        return True

    def retry(self, job_id: str) -> bool:
        row = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None or row["status"] not in ("failed", "cancelled"):
            return False
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'queued', cancel_requested = 0, error = NULL, progress = 0, finished_at = NULL WHERE id = ?",
                (job_id,),
            )
            if row["import_id"]:
                conn.execute("UPDATE imports SET status = 'queued', cancel_requested = 0 WHERE id = ?", (row["import_id"],))
        self.notify()
        return True

    # ---- trabajos --------------------------------------------------------
    def _run_import(self, job: dict) -> None:
        import_id = job["import_id"]
        job_id = job["id"]

        def should_cancel() -> bool:
            row = self.db.one("SELECT cancel_requested FROM imports WHERE id = ?", (import_id,))
            return bool(row and row["cancel_requested"]) or self._cancel_requested(job_id) or self._stop.is_set()

        def on_progress(stats: dict) -> None:
            total = stats["total_files"] or 1
            with self.db.tx() as conn:
                conn.execute(
                    "UPDATE imports SET total_files = ?, processed = ?, added = ?, updated = ?, unchanged = ?, offline = ?, errors = ? WHERE id = ?",
                    (stats["total_files"], stats["processed"], stats["added"], stats["updated"], stats["unchanged"], stats["offline"], json.dumps(stats["errors"]), import_id),
                )
                conn.execute("UPDATE jobs SET progress = ?, message = ? WHERE id = ?", (stats["processed"] / total, f"{stats['processed']}/{stats['total_files']} archivos", job_id))
            self.notify()

        try:
            stats = run_import(self.db, self.settings, import_id, should_cancel, on_progress)
        except ImportCancelled:
            with self.db.tx() as conn:
                conn.execute("UPDATE imports SET status = 'cancelled', finished_at = ?, message = 'Cancelada; lo ya incorporado se conserva' WHERE id = ?", (now_iso(), import_id))
            raise
        except Exception as exc:
            with self.db.tx() as conn:
                conn.execute("UPDATE imports SET status = 'failed', finished_at = ?, message = ? WHERE id = ?", (now_iso(), str(exc), import_id))
            raise
        with self.db.tx() as conn:
            msg = f"{stats['added']} nuevos, {stats['updated']} actualizados, {stats['unchanged']} sin cambios, {stats['offline']} offline, {len(stats['errors'])} errores"
            conn.execute("UPDATE imports SET status = 'done', finished_at = ?, message = ? WHERE id = ?", (now_iso(), msg, import_id))
        self.notify()

    def _run_analyze(self, job: dict) -> None:
        version_id = job["version_id"]
        job_id = job["id"]
        with self.db.tx() as conn:
            conn.execute("UPDATE asset_versions SET analysis_status = 'running', analysis_error = NULL WHERE id = ?", (version_id,))
        path = original_path_for_version(self.db, self.settings, version_id)
        if path is None:
            with self.db.tx() as conn:
                conn.execute("UPDATE asset_versions SET analysis_status = 'failed', analysis_error = ? WHERE id = ?", ("Original no accesible (fuente offline)", version_id))
            raise RuntimeError("Original no accesible: la fuente está offline")
        tools = resolve_tools(self.settings)
        try:
            analysis = probe_file(tools, path, self.settings.ffmpeg_timeout, self._register(job_id))
        except MediaError as exc:
            with self.db.tx() as conn:
                conn.execute("UPDATE asset_versions SET analysis_status = 'failed', analysis_error = ? WHERE id = ?", (str(exc), version_id))
            raise
        if self._cancel_requested(job_id):
            with self.db.tx() as conn:
                conn.execute("UPDATE asset_versions SET analysis_status = 'pending' WHERE id = ?", (version_id,))
            raise JobCancelled()
        kinds = plan_derivatives(analysis)
        now = now_iso()
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE asset_versions SET analysis_status = 'done', analysis = ?, analyzed_at = ?, media_kind = ? WHERE id = ?",
                (json.dumps(analysis), now, analysis.get("media_kind", "other"), version_id),
            )
            for kind in kinds:
                existing = conn.execute("SELECT id, status, recipe FROM derivatives WHERE version_id = ? AND kind = ?", (version_id, kind)).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO derivatives(id, version_id, kind, recipe, mime, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                        (new_id("der"), version_id, kind, RECIPES[kind], derivative_mime(kind), now, now),
                    )
                elif existing["recipe"] != RECIPES[kind] or existing["status"] in ("failed",):
                    conn.execute("UPDATE derivatives SET status = 'pending', recipe = ?, error = NULL, updated_at = ? WHERE id = ?", (RECIPES[kind], now, existing["id"]))
            if kinds:
                pending = conn.execute("SELECT id FROM jobs WHERE version_id = ? AND kind = 'derive' AND status IN ('queued','running')", (version_id,)).fetchone()
                if pending is None:
                    conn.execute(
                        "INSERT INTO jobs(id, kind, version_id, status, payload, created_at) VALUES (?, 'derive', ?, 'queued', '{}', ?)",
                        (new_id("job"), version_id, now),
                    )
        self.notify()

    def _run_derive(self, job: dict) -> None:
        version_id = job["version_id"]
        job_id = job["id"]
        version = self.db.one("SELECT * FROM asset_versions WHERE id = ?", (version_id,))
        if version is None or version["analysis_status"] != "done":
            raise RuntimeError("La versión no está analizada")
        analysis = loads(version["analysis"], {})
        path = original_path_for_version(self.db, self.settings, version_id)
        if path is None:
            raise RuntimeError("Original no accesible: la fuente está offline")
        tools = resolve_tools(self.settings)
        rows = self.db.query("SELECT * FROM derivatives WHERE version_id = ? AND status IN ('pending','failed') ORDER BY kind", (version_id,))
        failures: list[str] = []
        base = self.settings.derivatives_dir / version_id[-2:] / version_id
        for index, row in enumerate(rows):
            if self._cancel_requested(job_id) or self._stop.is_set():
                raise JobCancelled()
            kind = row["kind"]
            self._progress(job_id, index / max(1, len(rows)), f"Generando {kind}")
            dest = base / derivative_filename(kind)
            rel = dest.relative_to(self.settings.derivatives_dir).as_posix()
            started = time.perf_counter()
            try:
                info = generate_derivative(self.settings, tools, kind, path, analysis, dest, self._register(job_id))
                elapsed = round(time.perf_counter() - started, 2)
                with self.db.tx() as conn:
                    conn.execute(
                        "UPDATE derivatives SET status = 'ready', rel_path = ?, width = ?, height = ?, error = NULL, updated_at = ? WHERE id = ?",
                        (rel, info.get("width"), info.get("height"), now_iso(), row["id"]),
                    )
                log.info("Derivado %s de %s listo en %ss", kind, version_id, elapsed)
            except Exception as exc:
                if self._cancel_requested(job_id):
                    raise JobCancelled()
                failures.append(f"{kind}: {exc}")
                with self.db.tx() as conn:
                    conn.execute("UPDATE derivatives SET status = 'failed', error = ?, updated_at = ? WHERE id = ?", (str(exc), now_iso(), row["id"]))
        if failures:
            raise RuntimeError("; ".join(failures))
        self._progress(job_id, 1.0, "Derivados listos")

    def _run_index_pack(self, job: dict) -> None:
        from .packs import index_pack

        payload = loads(job["payload"], {})
        job_id = job["id"]
        stats = index_pack(
            self.db, self.settings, payload["pack_id"],
            lambda: self._cancel_requested(job_id) or self._stop.is_set(),
            lambda p, m: self._progress(job_id, p, m),
        )
        self._progress(job_id, 1.0, f"{stats['media']} recursos catalogados ({stats['new_assets']} nuevos), {stats['unsafe']} entradas rechazadas")
        self.notify()

    def _run_extract(self, job: dict) -> None:
        from .packs import DiskLimitError, PackError, extract_entry, select_entries

        payload = loads(job["payload"], {})
        job_id = job["id"]
        pack = self.db.one("SELECT * FROM packs WHERE id = ?", (payload["pack_id"],))
        if pack is None:
            raise RuntimeError("Pack inexistente")
        pack = dict(pack)
        entries = select_entries(self.db, pack["id"], payload.get("prefix", ""), payload.get("entry_ids"))
        total_bytes = sum(e["size"] for e in entries) or 1
        done_bytes = 0
        failures: list[str] = []
        extracted = 0

        def should_cancel() -> bool:
            return self._cancel_requested(job_id) or self._stop.is_set()

        for index, entry in enumerate(entries):
            if should_cancel():
                raise JobCancelled()
            self._progress(job_id, done_bytes / total_bytes, f"{index}/{len(entries)} · {entry['file_name']}")
            progress_ref = {"bytes": done_bytes, "last": 0.0}

            def on_bytes(n: int) -> None:
                progress_ref["bytes"] += n
                frac = progress_ref["bytes"] / total_bytes
                if frac - progress_ref["last"] >= 0.01:
                    progress_ref["last"] = frac
                    self._progress(job_id, frac, None)

            try:
                extract_entry(self.db, self.settings, pack, entry, should_cancel, on_bytes)
                extracted += 1
            except (ImportCancelled, JobCancelled):
                raise
            except DiskLimitError as exc:
                with self.db.tx() as conn:
                    conn.execute("UPDATE pack_entries SET error = ? WHERE id = ?", (str(exc), entry["id"]))
                failures.append(str(exc))
                break  # sin espacio: se detiene el lote; lo extraído se conserva
            except Exception as exc:
                with self.db.tx() as conn:
                    conn.execute("UPDATE pack_entries SET status = 'failed', error = ? WHERE id = ?", (str(exc), entry["id"]))
                failures.append(f"{entry['inner_path']}: {exc}")
            done_bytes += entry["size"]
            self.notify()
        msg = f"{extracted}/{len(entries)} extraídas"
        if failures:
            raise RuntimeError(msg + " · " + "; ".join(failures[:5]) + (f" (+{len(failures) - 5})" if len(failures) > 5 else ""))
        self._progress(job_id, 1.0, msg)


    def _run_backup(self, job: dict) -> None:
        from .backup import create_backup

        payload = loads(job["payload"], {})
        self._progress(job["id"], 0.1, "Copiando catálogo y derivados")
        result = create_backup(self.db, self.settings, payload.get("label", ""))
        self._progress(job["id"], 0.9, f"Snapshot {Path(result['path']).name}")
        if payload.get("upload") and self.settings.drive_configured:
            self._upload_backup_to_drive(job["id"], result)
        self._progress(job["id"], 1.0, f"Respaldo creado: {result['assets']} fichas, {result['derivatives_files']} derivados")

    def _upload_backup_to_drive(self, job_id: str, result: dict) -> None:
        import shutil
        import tempfile

        from .drive import DriveClient, mime_for

        folder = Path(result["path"])
        tmp_zip = Path(tempfile.mkdtemp(prefix="trama-bak-")) / (folder.name + ".zip")
        shutil.make_archive(str(tmp_zip.with_suffix("")), "zip", folder)
        client = DriveClient(self.settings, getattr(self, "drive_transport", None))
        try:
            size = tmp_zip.stat().st_size
            session = client.start_upload(tmp_zip.name, size, mime_for(".zip"), client.ensure_folder(), {"trama": "backup"})
            meta = client.upload_file(tmp_zip, session, size, 0, lambda b: self._progress(job_id, 0.9 + 0.1 * b / max(1, size), "Subiendo respaldo a Drive"))
            with self.db.tx() as conn:
                conn.execute("UPDATE backups SET status = 'uploaded', drive_file_id = ? WHERE id = ?", (meta.get("id"), result["id"]))
        finally:
            client.close()
            shutil.rmtree(tmp_zip.parent, ignore_errors=True)

    def _run_drive_upload(self, job: dict) -> None:
        """Sube un original a la carpeta privada de Drive. Reanudable: la sesión y el offset se
        guardan en el payload; verificable: md5 local contra md5Checksum de Drive."""
        from .drive import DriveClient, DriveError, md5_of, mime_for

        job_id = job["id"]
        payload = loads(job["payload"], {})
        version_id = job["version_id"]
        existing = self.db.one("SELECT id, external_id FROM locations WHERE version_id = ? AND kind = 'drive' AND status = 'available'", (version_id,))
        if existing:
            self._progress(job_id, 1.0, "Ya estaba en Drive")
            return
        path = original_path_for_version(self.db, self.settings, version_id)
        if path is None:
            raise RuntimeError("Original no accesible localmente: no se puede subir")
        version = self.db.one("SELECT * FROM asset_versions WHERE id = ?", (version_id,))
        size = path.stat().st_size
        client = DriveClient(self.settings, getattr(self, "drive_transport", None))
        try:
            folder_id = client.ensure_folder()
            session = payload.get("session_uri")
            offset = 0
            if session:
                try:
                    offset = client.upload_status(session, size)
                except DriveError:
                    session = None
            if not session:
                session = client.start_upload(path.name, size, mime_for(version["ext"]), folder_id, {"trama_version": version_id, "sha256": version["sha256"]})
                offset = 0
                with self.db.tx() as conn:
                    conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", (json.dumps({**payload, "session_uri": session}), job_id))

            def on_progress(sent: int) -> None:
                self._progress(job_id, 0.05 + 0.85 * sent / max(1, size), f"{sent // 2**20} / {size // 2**20} MB")
                with self.db.tx() as conn:
                    conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", (json.dumps({**payload, "session_uri": session, "bytes_sent": sent}), job_id))

            self._progress(job_id, 0.05, f"Reanudando desde {offset // 2**20} MB" if offset else "Subiendo")
            meta = client.upload_file(path, session, size, offset, on_progress, lambda: self._cancel_requested(job_id) or self._stop.is_set())
            self._progress(job_id, 0.92, "Verificando md5")
            local_md5 = md5_of(path)
            remote_md5 = meta.get("md5Checksum")
            if remote_md5 and remote_md5 != local_md5:
                client.delete_file(meta["id"])
                raise RuntimeError(f"Verificación fallida: md5 local {local_md5} ≠ Drive {remote_md5}; archivo remoto eliminado")
            source_id = ensure_drive_source(self.db, folder_id)
            now = now_iso()
            with self.db.tx() as conn:
                conn.execute(
                    "INSERT INTO locations(id, version_id, source_id, rel_path, file_name, size, mtime, status, last_seen_at, kind, external_id, checksum, verified_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, 'drive', ?, ?, ?)",
                    (new_id("loc"), version_id, source_id, f"drive:{meta['id']}", path.name, size, time.time(), now, meta["id"], remote_md5 or local_md5, now),
                )
            self._progress(job_id, 1.0, "Subido y verificado")
        finally:
            client.close()


    def _run_pack_upload(self, job: dict) -> None:
        """Sube el ZIP de un pack tal cual a TRAMA/Packs en Drive. Reanudable (sesión y offset en el
        payload) y verificado: md5 local contra md5Checksum de Drive antes de registrar la copia."""
        from .drive import DriveClient, DriveError, md5_of
        from .packs import pack_zip_path

        job_id = job["id"]
        payload = loads(job["payload"], {})
        pack = self.db.one("SELECT * FROM packs WHERE id = ?", (payload["pack_id"],))
        if pack is None:
            raise RuntimeError("Pack inexistente")
        pack = dict(pack)
        if pack.get("drive_file_id") and pack.get("drive_verified_at"):
            self._progress(job_id, 1.0, "Ya estaba en Drive")
            return
        path = pack_zip_path(self.settings, pack)
        if path is None or not path.is_file():
            raise RuntimeError("El ZIP no está en este equipo: no se puede subir")
        size = path.stat().st_size
        client = DriveClient(self.settings, getattr(self, "drive_transport", None))
        try:
            folder_id = client.ensure_subfolder("Packs", client.ensure_folder())
            session = payload.get("session_uri")
            offset = 0
            if session:
                try:
                    offset = client.upload_status(session, size)
                except DriveError:
                    session = None
            if not session:
                session = client.start_upload(path.name, size, "application/zip", folder_id, {"trama_pack": pack["id"]})
                offset = 0
                with self.db.tx() as conn:
                    conn.execute("UPDATE jobs SET payload = ? WHERE id = ?", (json.dumps({**payload, "session_uri": session}), job_id))

            def on_progress(sent: int) -> None:
                self._progress(job_id, 0.02 + 0.9 * sent / max(1, size), f"{pack['label']} · {sent // 2**20} / {size // 2**20} MB")

            self._progress(job_id, 0.02, f"{pack['label']} · reanudando desde {offset // 2**20} MB" if offset else f"{pack['label']} · subiendo")
            meta = client.upload_file(path, session, size, offset, on_progress, lambda: self._cancel_requested(job_id) or self._stop.is_set())
            self._progress(job_id, 0.94, f"{pack['label']} · verificando md5")
            local_md5 = md5_of(path)
            remote_md5 = meta.get("md5Checksum")
            if not remote_md5 or remote_md5 != local_md5:
                client.delete_file(meta["id"])
                raise RuntimeError(f"Verificación fallida: md5 local {local_md5} ≠ Drive {remote_md5}; copia remota eliminada")
            with self.db.tx() as conn:
                conn.execute(
                    "UPDATE packs SET drive_file_id = ?, drive_md5 = ?, drive_verified_at = ? WHERE id = ?",
                    (meta["id"], remote_md5, now_iso(), pack["id"]),
                )
            self._progress(job_id, 1.0, f"{pack['label']} · subido y verificado")
        finally:
            client.close()


def enqueue_pack_upload(db: Database, pack_id: str) -> str | None:
    now = now_iso()
    with db.tx() as conn:
        pack = conn.execute("SELECT drive_file_id, drive_verified_at FROM packs WHERE id = ?", (pack_id,)).fetchone()
        if pack is None:
            return None
        if pack["drive_file_id"] and pack["drive_verified_at"]:
            return None
        pending = conn.execute("SELECT id FROM jobs WHERE kind = 'pack_upload' AND status IN ('queued','running') AND json_extract(payload, '$.pack_id') = ?", (pack_id,)).fetchone()
        if pending:
            return pending["id"]
        job_id = new_id("job")
        conn.execute(
            "INSERT INTO jobs(id, kind, status, payload, created_at, max_attempts) VALUES (?, 'pack_upload', 'queued', ?, ?, 5)",
            (job_id, json.dumps({"pack_id": pack_id}), now),
        )
    return job_id


def ensure_drive_source(db: Database, folder_id: str) -> str:
    source_id = f"drive_{folder_id[:12]}"
    if db.one("SELECT id FROM sources WHERE id = ?", (source_id,)) is None:
        with db.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sources(id, kind, label, root_path, created_at) VALUES (?, 'drive', 'Google Drive', ?, ?)",
                (source_id, f"drive:{folder_id}", now_iso()),
            )
    return source_id


def enqueue_drive_upload(db: Database, version_id: str) -> str | None:
    now = now_iso()
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM locations WHERE version_id = ? AND kind = 'drive' AND status = 'available'", (version_id,)).fetchone():
            return None
        pending = conn.execute("SELECT id FROM jobs WHERE kind = 'drive_upload' AND version_id = ? AND status IN ('queued','running')", (version_id,)).fetchone()
        if pending:
            return pending["id"]
        job_id = new_id("job")
        conn.execute(
            "INSERT INTO jobs(id, kind, version_id, status, payload, created_at, max_attempts) VALUES (?, 'drive_upload', ?, 'queued', '{}', ?, 5)",
            (job_id, version_id, now),
        )
    return job_id


def enqueue_backup(db: Database, label: str = "", upload: bool = False) -> str:
    now = now_iso()
    with db.tx() as conn:
        pending = conn.execute("SELECT id FROM jobs WHERE kind = 'backup' AND status IN ('queued','running')").fetchone()
        if pending:
            return pending["id"]
        job_id = new_id("job")
        conn.execute(
            "INSERT INTO jobs(id, kind, status, payload, created_at, max_attempts) VALUES (?, 'backup', 'queued', ?, ?, 1)",
            (job_id, json.dumps({"label": label, "upload": upload}), now),
        )
    return job_id


def enqueue_index_pack(db: Database, pack_id: str) -> str:
    now = now_iso()
    with db.tx() as conn:
        pending = conn.execute("SELECT id FROM jobs WHERE kind = 'index_pack' AND status IN ('queued','running') AND json_extract(payload, '$.pack_id') = ?", (pack_id,)).fetchone()
        if pending:
            return pending["id"]
        job_id = new_id("job")
        conn.execute(
            "INSERT INTO jobs(id, kind, status, payload, created_at, max_attempts) VALUES (?, 'index_pack', 'queued', ?, ?, 1)",
            (job_id, json.dumps({"pack_id": pack_id}), now),
        )
    return job_id


def enqueue_extract(db: Database, pack_id: str, prefix: str = "", entry_ids: list[str] | None = None) -> str:
    now = now_iso()
    payload = {"pack_id": pack_id, "prefix": prefix, "entry_ids": entry_ids or []}
    with db.tx() as conn:
        job_id = new_id("job")
        conn.execute(
            "INSERT INTO jobs(id, kind, status, payload, created_at, max_attempts) VALUES (?, 'extract', 'queued', ?, ?, 1)",
            (job_id, json.dumps(payload), now),
        )
    return job_id


def enqueue_import(db: Database, source_id: str, sub_path: str) -> dict:
    now = now_iso()
    import_id = new_id("imp")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO imports(id, source_id, sub_path, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (import_id, source_id, sub_path, now),
        )
        conn.execute(
            "INSERT INTO jobs(id, kind, import_id, status, payload, created_at) VALUES (?, 'import', ?, 'queued', ?, ?)",
            (new_id("job"), import_id, json.dumps({"source_id": source_id, "sub_path": sub_path}), now),
        )
    return dict(db.one("SELECT * FROM imports WHERE id = ?", (import_id,)))


def enqueue_reanalyze(db: Database, version_id: str) -> None:
    now = now_iso()
    with db.tx() as conn:
        conn.execute("UPDATE asset_versions SET analysis_status = 'pending', analysis_error = NULL WHERE id = ?", (version_id,))
        conn.execute("UPDATE derivatives SET status = 'pending', error = NULL, updated_at = ? WHERE version_id = ?", (now, version_id))
        conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ? WHERE version_id = ? AND status = 'queued'", (now, version_id))
        conn.execute(
            "INSERT INTO jobs(id, kind, version_id, status, payload, created_at) VALUES (?, 'analyze', ?, 'queued', ?, ?)",
            (new_id("job"), version_id, json.dumps({"reason": "reanalyze"}), now),
        )
