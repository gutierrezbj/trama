"""Pruebas de persistencia, reimportación, archivos y seguridad (E1)."""
from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

from conftest import import_all, reopen, source_id, wait_idle


def test_import_analyzes_and_generates_real_derivatives(env):
    client = env["client"]
    imp = import_all(client)
    assert imp["status"] == "done"
    assert imp["added"] == 4
    assert imp["errors"] == []  # el archivo roto se cataloga; el fallo aparece en el análisis

    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    by_title = {a["original_title"]: a for a in items}
    assert set(by_title) == {"test_opaque.mp4", "test_alpha.mov", "test_tone.wav", "roto.mp4"}

    opaque = by_title["test_opaque.mp4"]
    assert opaque["version"]["analysis_status"] == "done"
    assert abs(opaque["summary"]["duration_s"] - 2.0) < 0.05
    assert (opaque["summary"]["width"], opaque["summary"]["height"]) == (320, 180)
    assert opaque["summary"]["alpha_format"] is False
    assert opaque["preview"] == {"kind": "video", "status": "ready", "backgrounds": []}
    assert opaque["category"] == "transiciones"  # inferida de la carpeta

    alpha = by_title["test_alpha.mov"]
    assert alpha["summary"]["alpha_format"] is True
    assert alpha["summary"]["alpha_used"] is True
    assert alpha["summary"]["orientation"] == "vertical"
    assert alpha["preview"]["kind"] == "video_alpha"
    assert alpha["preview"]["status"] == "ready"
    for bg in ("dark", "light", "checker"):
        r = client.get(f"/api/assets/{alpha['id']}/preview", params={"bg": bg})
        assert r.status_code == 200 and r.headers["content-type"].startswith("video/mp4") and len(r.content) > 500
    thumb = client.get(f"/api/assets/{alpha['id']}/thumb")
    assert thumb.status_code == 200 and thumb.content[:3] == b"\xff\xd8\xff"

    audio = by_title["test_tone.wav"]
    assert audio["category"] == "audio"
    assert audio["summary"]["sample_rate"] == 44100
    assert audio["waveform_url"]
    assert client.get(audio["waveform_url"]).content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/assets/{audio['id']}/preview").headers["content-type"].startswith("audio/mp4")

    broken = by_title["roto.mp4"]
    assert broken["version"]["analysis_status"] == "failed"
    assert broken["version"]["analysis_error"]
    assert broken["preview"]["status"] == "failed"
    failed_jobs = client.get("/api/jobs", params={"status": "failed"}).json()
    assert any(j["asset_id"] == broken["id"] for j in failed_jobs)


def test_reimport_is_idempotent_and_keeps_edits(env):
    client = env["client"]
    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    asset = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    client.patch(f"/api/assets/{asset['id']}", json={"title": "Barrido de prueba", "tags": ["barrido", "Barrido", "azul"], "description": "  editada  ", "category": "overlays"})

    imp2 = import_all(client)
    assert imp2["added"] == 0 and imp2["unchanged"] == 4
    assert client.get("/api/assets").json()["total"] == 4
    again = client.get(f"/api/assets/{asset['id']}").json()
    assert again["title"] == "Barrido de prueba"
    assert again["tags"] == ["barrido", "azul"]  # duplicados normalizados
    assert again["description"] == "editada" and again["description_source"] == "human"
    assert again["category"] == "overlays" and again["category_source"] == "human"

    # Copia con otro nombre = mismos bytes → misma ficha, segunda ubicación, sin duplicar.
    src = env["files"]["opaque"]
    shutil.copy2(src, src.with_name("copia_" + src.name))
    imp3 = import_all(client)
    assert imp3["added"] == 0
    assert client.get("/api/assets").json()["total"] == 4
    detail = client.get(f"/api/assets/{asset['id']}").json()
    assert len(detail["locations"]) == 2

    # Búsqueda sin acentos ni mayúsculas sobre título, etiquetas y descripción.
    assert client.get("/api/assets", params={"q": "BARRIDO"}).json()["total"] == 1
    assert client.get("/api/assets", params={"q": "édítada"}).json()["total"] == 1
    assert client.get("/api/assets", params={"q": "inexistente"}).json()["total"] == 0


def test_persistence_survives_restart_and_offline_source(env):
    client = env["client"]
    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    alpha = next(a for a in items if a["original_title"] == "test_alpha.mov")
    client.patch(f"/api/assets/{alpha['id']}", json={"favorite": True})
    sel = client.post("/api/selections", json={"name": "Spot", "notes": "n"}).json()
    client.put(f"/api/selections/{sel['id']}/items/{alpha['id']}")
    client.put(f"/api/selections/{sel['id']}/items/{alpha['id']}")  # idempotente
    col = client.post("/api/collections", json={"name": "Humo"}).json()
    client.put(f"/api/collections/{col['id']}/assets/{alpha['id']}")

    client = reopen(env)
    after = client.get(f"/api/assets/{alpha['id']}").json()
    assert after["favorite"] is True
    assert after["preview"]["status"] == "ready"  # derivados conservados, sin regenerar
    s = client.get(f"/api/selections/{sel['id']}").json()
    assert [i["id"] for i in s["items"]] == [alpha["id"]] and s["notes"] == "n"
    assert client.get(f"/api/collections/{col['id']}").json()["assets"][0]["id"] == alpha["id"]
    assert client.get("/api/jobs/summary").json()["totals"].get("running", 0) == 0

    # Fuente desconectada: la ficha y las previews siguen; el original no.
    original = env["files"]["alpha"]
    moved = env["tmp"] / "fuera.mov"
    original.rename(moved)
    r = client.get(f"/api/assets/{alpha['id']}/original")
    assert r.status_code == 404
    still = client.get(f"/api/assets/{alpha['id']}").json()
    assert still["available"] is False and still["preview"]["status"] == "ready"
    assert client.get(f"/api/assets/{alpha['id']}/thumb").status_code == 200
    assert client.get("/api/assets", params={"availability": "offline"}).json()["total"] == 1
    # Vuelve: se recupera sin crear otra ficha.
    moved.rename(original)
    imp = import_all(client)
    assert imp["added"] == 0
    assert client.get(f"/api/assets/{alpha['id']}").json()["available"] is True


def test_original_download_serves_exact_bytes_with_ranges(env):
    client = env["client"]
    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    audio = next(a for a in items if a["original_title"] == "test_tone.wav")
    raw = env["files"]["audio"].read_bytes()
    r = client.get(f"/api/assets/{audio['id']}/original")
    assert r.status_code == 200
    assert r.content == raw
    assert hashlib.sha256(r.content).hexdigest() == audio["version"]["sha256"]
    assert "attachment" in r.headers["content-disposition"] and "test_tone.wav" in r.headers["content-disposition"]
    part = client.get(f"/api/assets/{audio['id']}/original", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == raw[10:20]
    inline = client.get(f"/api/assets/{audio['id']}/original", params={"inline": 1})
    assert inline.headers["content-disposition"].startswith("inline")
    # El original no se ha tocado.
    assert env["files"]["audio"].read_bytes() == raw
    assert client.get("/api/assets/ast_inexistente/original").status_code == 404


def test_paths_never_escape_allowed_roots(env):
    client = env["client"]
    sid = source_id(client)
    for bad in ("..", "../..", "..\\..", "/etc", "C:\\Windows", "VFX/../../.."):
        r = client.get("/api/fs/browse", params={"source_id": sid, "path": bad})
        assert r.status_code in (400, 404), bad
        r = client.post("/api/imports", json={"source_id": sid, "path": bad})
        assert r.status_code in (400, 404), bad
    assert client.get("/api/fs/browse", params={"source_id": "src_falsa", "path": ""}).status_code == 404
    ok = client.get("/api/fs/browse", params={"source_id": sid, "path": "VFX"}).json()
    assert ok["path"] == "VFX" and ok["parent"] == "" and ok["media_files"] == 1
    # Un ID de recurso nunca es una ruta: nada de leer archivos arbitrarios.
    for probe in ("/api/assets/../../.env/original", "/api/assets/..%2F..%2F.env/original", "/../.env", "/.env", "/backend/trama/config.py"):
        r = client.get(probe)
        assert "TRAMA_" not in r.text and "load_settings" not in r.text, probe
        assert r.status_code in (404, 422) or r.headers["content-type"].startswith("text/html"), probe


def test_cancel_and_retry_jobs(env):
    client = env["client"]
    import_all(client)
    failed = client.get("/api/jobs", params={"status": "failed"}).json()
    assert failed, "el archivo roto debe dejar un trabajo fallido"
    job = failed[0]
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 200
    wait_idle(client)
    again = next(j for j in client.get("/api/jobs", params={"status": "failed"}).json() if j["id"] == job["id"])
    assert again["attempts"] == job["attempts"] + 1 and again["error"]
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200  # cancelar un fallido no rompe nada

    # Reanálisis explícito regenera derivados con nueva cola.
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    opaque = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    r = client.post(f"/api/assets/{opaque['id']}/reanalyze").json()
    assert r["version"]["analysis_status"] == "pending"
    wait_idle(client)
    assert client.get(f"/api/assets/{opaque['id']}").json()["preview"]["status"] == "ready"


def test_import_cancellation_keeps_partial_work(env, tools):
    client = env["client"]
    root: Path = env["root"]
    big = root / "grande.mp4"
    # Archivo grande para que el hash tarde lo suficiente como para cancelar a mitad.
    with open(big, "wb") as fh:
        for _ in range(60):
            fh.write(b"\0" * (4 * 1024 * 1024))
    imp = client.post("/api/imports", json={"source_id": source_id(client), "path": ""}).json()
    time.sleep(0.15)
    client.post(f"/api/imports/{imp['id']}/cancel")
    wait_idle(client)
    final = client.get(f"/api/imports/{imp['id']}").json()
    assert final["status"] in ("cancelled", "done")
    total = client.get("/api/assets").json()["total"]
    assert 0 <= total <= 5
    # Reimportar tras cancelar completa el lote sin duplicar.
    import_all(client)
    assert client.get("/api/assets").json()["total"] == 5
