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
    """Primera ubicación disponible cuyo archivo existe realmente. Marca offline las que no."""
    rows = db.query(
        "SELECT l.id, l.rel_path, l.status, l.source_id FROM locations l WHERE l.version_id = ? ORDER BY l.status = 'available' DESC, l.last_seen_at DESC",
        (version_id,),
    )
    for row in rows:
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
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY CASE kind WHEN 'import' THEN 0 WHEN 'analyze' THEN 1 ELSE 2 END, created_at LIMIT 1"
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
