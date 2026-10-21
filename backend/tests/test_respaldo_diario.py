"""Respaldo diario: copia comprimida restaurable, poda local y sin Drive cuando se pide."""
from __future__ import annotations

import gzip
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trama.config import Settings
from trama.db import Database
from trama.respaldo_diario import crear, ejecutar, podar


def _settings(tmp_path: Path) -> Settings:
    s = Settings(data_dir=tmp_path / "data", allowed_roots=[])
    s.ensure_dirs()
    Database(s.db_path).migrate()
    with sqlite3.connect(s.db_path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS prueba_respaldo(x TEXT)")
        c.execute("INSERT INTO prueba_respaldo VALUES ('pez')")
    return s


def test_copia_restaurable_y_poda(tmp_path: Path):
    s = _settings(tmp_path)
    for dia in (1, 2, 3):
        crear(s, datetime(2026, 10, dia, 4, tzinfo=timezone.utc))
    carpeta = s.data_dir / "respaldos" / "diario"
    assert [p.name for p in sorted(carpeta.glob("*.gz"))] == [
        "catalogo-2026-10-01.sqlite.gz", "catalogo-2026-10-02.sqlite.gz", "catalogo-2026-10-03.sqlite.gz"]
    # la copia se descomprime y abre como base válida con los datos
    plano = tmp_path / "restaurada.sqlite"
    plano.write_bytes(gzip.decompress((carpeta / "catalogo-2026-10-03.sqlite.gz").read_bytes()))
    with sqlite3.connect(plano) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT x FROM prueba_respaldo").fetchone()[0] == "pez"
    fuera = podar(carpeta, 2)
    assert [p.name for p in fuera] == ["catalogo-2026-10-01.sqlite.gz"]
    assert len(list(carpeta.glob("*.gz"))) == 2
    assert not list(carpeta.glob("*.tmp")) and not (carpeta / "_copia.sqlite").exists()


def test_ejecutar_sin_drive(tmp_path: Path):
    s = _settings(tmp_path)
    r = ejecutar(s, conservar=14, drive=False)
    assert Path(r["copia"]).exists() and r["drive"] is None and r["borradas"] == []
