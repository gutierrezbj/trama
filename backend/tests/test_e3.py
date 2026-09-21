"""E3: acceso privado, respaldos con restauración ensayada y adaptador Drive (servidor simulado)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import httpx
import pytest
from conftest import import_all, wait_idle
from fastapi.testclient import TestClient

from trama.api import create_app
from trama.auth import hash_password
from trama.config import Settings
from trama.db import Database


# ------------------------------------------------------------------ acceso

@pytest.fixture
def private(tmp_path: Path, tools):
    from conftest import make_fixture_files

    root = tmp_path / "raiz"
    make_fixture_files(tools, root)
    settings = Settings(
        data_dir=tmp_path / "datos", allowed_roots=[root], workers=1, ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe,
        auth_mode="password", password_hash=hash_password("clave-muy-secreta"), api_tokens=["token-escenda"],
    )
    app = create_app(settings, start_worker=True)
    client = TestClient(app)
    client.__enter__()
    yield client, settings, app.state.trama
    client.__exit__(None, None, None)
    app.state.trama.db.close()


def test_everything_requires_login_including_media(private):
    client, settings, state = private
    st = client.get("/api/auth/status").json()
    assert st["mode"] == "password" and st["authenticated"] is False and st["misconfigured"] is False
    for path in ("/api/assets", "/api/config", "/api/packs", "/api/backups", "/api/assets/x/original", "/api/assets/x/thumb", "/api/fs/sources", "/api/drive/status"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/docs").status_code in (401, 404)
    # La interfaz (código estático) sí se sirve; los datos no.
    assert client.get("/").status_code == 200

    assert client.post("/api/auth/login", json={"password": "incorrecta"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "clave-muy-secreta"})
    assert r.status_code == 200 and "trama_session" in r.cookies
    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/assets").status_code == 200
    # Con sesión, incorporar y servir medios funciona.
    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    opaque = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    assert client.get(f"/api/assets/{opaque['id']}/thumb").status_code == 200
    assert client.get(f"/api/assets/{opaque['id']}/original").status_code == 200
    # Cerrar sesión bloquea otra vez; cookie manipulada no vale.
    client.post("/api/auth/logout")
    assert client.get("/api/assets").status_code == 401
    client.cookies.set("trama_session", "abc.def")
    assert client.get("/api/assets").status_code == 401
    client.cookies.clear()
    # Token portador para integraciones.
    assert client.get("/api/assets", headers={"Authorization": "Bearer token-escenda"}).status_code == 200
    assert client.get("/api/assets", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_login_lockout_after_failures(private):
    client, settings, state = private
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "no"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "clave-muy-secreta"})
    assert r.status_code == 429 and "espera" in r.json()["detail"]
    state.guard.reset("testclient")
    assert client.post("/api/auth/login", json={"password": "clave-muy-secreta"}).status_code == 200


def test_misconfigured_password_mode_is_reported(tmp_path, tools):
    settings = Settings(data_dir=tmp_path / "d", allowed_roots=[], auth_mode="password", password_hash=None, ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        st = client.get("/api/auth/status").json()
        assert st["misconfigured"] is True
        assert client.post("/api/auth/login", json={"password": "lo-que-sea"}).status_code == 401
    app.state.trama.db.close()


# ------------------------------------------------------------------ respaldos

def test_backup_and_restore_round_trip(env):
    from trama.backup import BackupError, create_backup, restore_backup, verify_backup

    client = env["client"]
    settings = env["settings"]
    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    alpha = next(a for a in items if a["original_title"] == "test_alpha.mov")
    client.patch(f"/api/assets/{alpha['id']}", json={"tags": ["respaldado"], "favorite": True})
    sel = client.post("/api/selections", json={"name": "Antes del respaldo"}).json()
    client.put(f"/api/selections/{sel['id']}/items/{alpha['id']}")

    r = client.post("/api/backups", json={"label": "prueba"})
    assert r.status_code == 202
    wait_idle(client)
    listing = client.get("/api/backups").json()
    assert len(listing["backups"]) == 1 and listing["backups"][0]["present"] is True
    bak = listing["backups"][0]
    folder = Path(bak["path"])
    assert (folder / "manifest.json").is_file() and (folder / "catalogo.sqlite").is_file()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"] == 4 and manifest["derivatives_files"] > 0
    assert client.get(f"/api/backups/{bak['id']}/verify").json()["ok"] is True

    # Destrozamos el estado vivo: borramos la ficha editada y los derivados.
    client.delete(f"/api/selections/{sel['id']}")
    with env["state"].db.tx() as conn:
        conn.execute("DELETE FROM selection_items")
        conn.execute("UPDATE assets SET tags = '[]', favorite = 0")
    shutil.rmtree(settings.derivatives_dir)
    assert client.get(f"/api/assets/{alpha['id']}").json()["tags"] == []

    # Restauración ensayada con el servidor parado.
    env["client"].__exit__(None, None, None)
    env["state"].db.close()
    result = restore_backup(settings, folder)
    assert result["assets"] == 4
    app = create_app(settings, start_worker=True)
    client = TestClient(app)
    client.__enter__()
    env["client"], env["state"] = client, app.state.trama
    again = client.get(f"/api/assets/{alpha['id']}").json()
    assert again["tags"] == ["respaldado"] and again["favorite"] is True
    assert again["preview"]["status"] == "ready" and client.get(f"/api/assets/{alpha['id']}/thumb").status_code == 200
    assert [s["name"] for s in client.get("/api/selections").json()] == ["Antes del respaldo"]
    assert any(p.name.startswith("catalogo.sqlite.pre-restore") for p in settings.data_dir.iterdir())

    # Respaldo corrupto: se detecta antes de restaurar.
    (folder / "catalogo.sqlite").write_bytes(b"basura")
    with pytest.raises(BackupError):
        verify_backup(folder)

    # Retención: solo se conservan `backup_keep` snapshots.
    settings.backup_keep = 2
    for i in range(3):
        create_backup(env["state"].db, settings, f"r{i}")
    kept = [b for b in client.get("/api/backups").json()["backups"]]
    assert len(kept) == 2 and all(b["present"] for b in kept)


# ------------------------------------------------------------------ Drive simulado

class FakeDrive:
    """Servidor Drive mínimo: token, about, carpeta, subida reanudable con una interrupción, get y descarga con rangos."""

    def __init__(self, fail_once_at_chunk: int | None = 2):
        self.files: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.fail_once_at_chunk = fail_once_at_chunk
        self.chunks_seen = 0
        self.token_refreshes = 0
        self.n = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url, path, method = request.url, request.url.path, request.method
        if path == "/token":
            body = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if body.get("grant_type") == "authorization_code":
                assert body["code"] == "codigo-ok" and body.get("code_verifier")
                return httpx.Response(200, json={"access_token": "at1", "refresh_token": "rt1", "expires_in": 3600})
            self.token_refreshes += 1
            return httpx.Response(200, json={"access_token": f"at{self.token_refreshes + 1}", "expires_in": 3600})
        assert request.headers.get("Authorization", "").startswith("Bearer "), "petición sin token"
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"emailAddress": "prueba@example.com"}, "storageQuota": {"usage": "10", "limit": "100"}})
        if path == "/drive/v3/files" and method == "GET":
            return httpx.Response(200, json={"files": [f for f in self.files.values() if f.get("mimeType") == "application/vnd.google-apps.folder"]})
        if path == "/drive/v3/files" and method == "POST":
            meta = json.loads(request.content)
            self.n += 1
            fid = f"folder{self.n}"
            self.files[fid] = {"id": fid, "name": meta["name"], "mimeType": meta["mimeType"], "trashed": False}
            return httpx.Response(200, json={"id": fid})
        if path == "/upload/drive/v3/files" and method == "POST":
            meta = json.loads(request.content)
            self.n += 1
            sid = f"sess{self.n}"
            self.sessions[sid] = {"meta": meta, "size": int(request.headers["X-Upload-Content-Length"]), "data": bytearray()}
            return httpx.Response(200, headers={"Location": f"https://upload.example/{sid}"})
        if url.host == "upload.example":
            sess = self.sessions[path.strip("/")]
            crange = request.headers.get("Content-Range", "")
            m = re.match(r"bytes (\*|(\d+)-(\d+))/(\d+)", crange)
            if m.group(1) == "*":
                if len(sess["data"]) >= sess["size"]:
                    return httpx.Response(200, json=self._finish(sess))
                return httpx.Response(308, headers={"Range": f"bytes=0-{len(sess['data']) - 1}"} if sess["data"] else {})
            start, end = int(m.group(2)), int(m.group(3))
            self.chunks_seen += 1
            if self.fail_once_at_chunk is not None and self.chunks_seen == self.fail_once_at_chunk:
                self.fail_once_at_chunk = None
                # Interrupción: solo se guarda la mitad del trozo, y el cliente debe consultar el estado.
                half = request.content[: len(request.content) // 2]
                sess["data"][start:start + len(half)] = half
                del sess["data"][start + len(half):]
                return httpx.Response(503)
            assert start == len(sess["data"]), f"trozo fuera de orden: {start} != {len(sess['data'])}"
            sess["data"] += request.content
            if len(sess["data"]) >= sess["size"]:
                return httpx.Response(200, json=self._finish(sess))
            return httpx.Response(308, headers={"Range": f"bytes=0-{len(sess['data']) - 1}"})
        m = re.match(r"/drive/v3/files/([^/]+)$", path)
        if m and method == "GET":
            f = self.files.get(m.group(1))
            if f is None:
                return httpx.Response(404)
            if url.params.get("alt") == "media":
                data = f["data"]
                rng = request.headers.get("Range")
                if rng:
                    a, b = rng.replace("bytes=", "").split("-")
                    a, b = int(a), int(b) if b else len(data) - 1
                    return httpx.Response(206, content=bytes(data[a:b + 1]), headers={"Content-Range": f"bytes {a}-{b}/{len(data)}", "Content-Length": str(b - a + 1), "Content-Type": "video/mp4"})
                return httpx.Response(200, content=bytes(data), headers={"Content-Length": str(len(data)), "Content-Type": "video/mp4"})
            return httpx.Response(200, json={k: v for k, v in f.items() if k != "data"})
        if m and method == "DELETE":
            self.files.pop(m.group(1), None)
            return httpx.Response(204)
        return httpx.Response(404, text=f"sin ruta: {method} {path}")

    def _finish(self, sess: dict) -> dict:
        self.n += 1
        fid = f"file{self.n}"
        data = bytes(sess["data"])
        self.files[fid] = {"id": fid, "name": sess["meta"]["name"], "size": str(len(data)), "md5Checksum": hashlib.md5(data).hexdigest(), "trashed": False, "data": data}
        return {"id": fid, "md5Checksum": self.files[fid]["md5Checksum"], "size": str(len(data))}


@pytest.fixture
def drive_env(tmp_path: Path, tools):
    from conftest import make_fixture_files

    root = tmp_path / "raiz"
    files = make_fixture_files(tools, root)
    data_dir = tmp_path / "datos"
    (data_dir / "drive").mkdir(parents=True)
    (data_dir / "drive" / "client_secret.json").write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}), encoding="utf-8")
    fake = FakeDrive()
    settings = Settings(
        data_dir=data_dir, allowed_roots=[root], workers=2, ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe,
        drive_client_file=data_dir / "drive" / "client_secret.json", drive_chunk_bytes=2048,
        drive_api_base="https://api.example", drive_oauth_base="https://oauth.example", drive_auth_base="https://auth.example/o/oauth2/v2/auth",
    )
    app = create_app(settings, start_worker=True, drive_transport=fake.transport())
    client = TestClient(app)
    client.__enter__()
    yield {"client": client, "settings": settings, "state": app.state.trama, "fake": fake, "files": files, "root": root}
    client.__exit__(None, None, None)
    app.state.trama.db.close()


def test_drive_oauth_upload_resume_verify_and_stream(drive_env):
    client, settings, fake, files = drive_env["client"], drive_env["settings"], drive_env["fake"], drive_env["files"]
    st = client.get("/api/drive/status").json()
    assert st["configured"] is True and st["connected"] is False
    # OAuth: URL con PKCE y alcance mínimo; callback con state válido guarda el token (solo backend).
    url = client.post("/api/drive/auth/start").json()["url"]
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file" in url and "code_challenge=" in url
    state = re.search(r"state=([^&]+)", url).group(1)
    assert client.get("/api/drive/auth/callback", params={"state": "falso", "code": "x"}).status_code == 400
    r = client.get("/api/drive/auth/callback", params={"state": state, "code": "codigo-ok"}, follow_redirects=False)
    assert r.status_code == 303 and settings.drive_token_file.is_file()
    st = client.get("/api/drive/status").json()
    assert st["connected"] is True and st["account"] == "prueba@example.com" and st["folder_id"]
    # Nada del token sale por la API.
    assert "rt1" not in json.dumps(st)

    import_all(client)
    items = client.get("/api/assets", params={"limit": 100}).json()["items"]
    opaque = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    raw = files["opaque"].read_bytes()
    assert len(raw) > 3 * settings.drive_chunk_bytes, "el fixture debe ocupar varios trozos"
    r = client.post(f"/api/assets/{opaque['id']}/drive-upload")
    assert r.status_code == 202 and r.json()["job_id"]
    wait_idle(client)
    jobs = [j for j in client.get("/api/jobs").json() if j["kind"] == "drive_upload"]
    assert jobs and jobs[0]["status"] == "done", jobs
    assert fake.fail_once_at_chunk is None, "debió producirse la interrupción simulada"
    a = client.get(f"/api/assets/{opaque['id']}").json()
    drive_loc = next(l for l in a["locations"] if l["kind"] == "drive")
    assert a["in_drive"] is True and drive_loc["status"] == "available" and drive_loc["external_id"].startswith("file")
    assert fake.files[drive_loc["external_id"]]["data"] == raw          # bytes exactos tras la reanudación
    assert drive_loc["checksum"] == hashlib.md5(raw).hexdigest()         # verificado por md5
    assert client.post(f"/api/assets/{opaque['id']}/drive-upload").json()["message"] == "Ya estaba en Drive"
    assert client.post(f"/api/assets/{opaque['id']}/drive-verify").json()["ok"] is True

    # Original solo en Drive (el local desaparece): se sirve en streaming con rangos, sin enlaces de Drive.
    files["opaque"].rename(files["opaque"].with_name("fuera.mp4"))
    a = client.get(f"/api/assets/{opaque['id']}").json()
    assert a["available"] is False and a["remote_available"] is True
    r = client.get(f"/api/assets/{opaque['id']}/original")
    assert r.status_code == 200 and r.content == raw and "attachment" in r.headers["content-disposition"]
    r = client.get(f"/api/assets/{opaque['id']}/original", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == raw[100:200]
    # Los derivados no dependen de Drive.
    assert client.get(f"/api/assets/{opaque['id']}/thumb").status_code == 200

    # Respaldo subido a Drive y desconexión.
    client.post("/api/backups", json={"label": "nube", "upload": True})
    wait_idle(client)
    b = client.get("/api/backups").json()["backups"][0]
    assert b["status"] == "uploaded" and b["drive_file_id"] in fake.files
    client.post("/api/drive/disconnect")
    assert client.get("/api/drive/status").json()["connected"] is False
    assert client.post(f"/api/assets/{opaque['id']}/drive-upload").status_code == 409


def test_drive_not_configured_is_explicit(env):
    client = env["client"]
    st = client.get("/api/drive/status").json()
    assert st["configured"] is False and st["connected"] is False
    assert client.post("/api/drive/auth/start").status_code == 409
    import_all(client)
    a = client.get("/api/assets").json()["items"][0]
    r = client.post(f"/api/assets/{a['id']}/drive-upload")
    assert r.status_code == 409 and "client_secret" in r.json()["detail"]
