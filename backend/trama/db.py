"""Acceso a SQLite: conexiones por hilo, migraciones numeradas y utilidades."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def normalize_text(text: str) -> str:
    """Minúsculas, sin acentos, separadores unificados. Base de la búsqueda textual E1."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[_\-\.\\/()\[\]]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self):
        """Transacción de escritura serializada dentro del proceso (un solo dueño del catálogo)."""
        with self._write_lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self._write_lock:
            conn = self.conn
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = int(file.name.split("_", 1)[0])
                if version in done:
                    continue
                sql = file.read_text(encoding="utf-8")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split_statements(sql):
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now_iso())
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                applied.append(version)
        return applied

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.split("--", 1)[0]
        buffer.append(stripped)
        if stripped.rstrip().endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement.strip(";").strip():
                statements.append(statement)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail.strip(";").strip():
        statements.append(tail)
    return statements


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def loads(value, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
