"""Adaptador de Google Drive: OAuth con alcance mínimo (`drive.file`), carpeta privada TRAMA,
subida reanudable y verificable (md5 del proveedor contra md5 local) y descarga con rangos.

Solo el backend guarda credenciales (client_secret.json y token.json en el directorio de datos,
nunca en el repositorio). No se crean enlaces públicos ni se comparte nada.
Implementado sobre httpx contra la API REST v3; probado contra un servidor simulado
(tests/test_drive.py). Mientras no exista un cliente OAuth, TRAMA informa «Drive no configurado».
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlencode

import httpx

from .config import Settings

SCOPE = "https://www.googleapis.com/auth/drive.file"


class DriveError(RuntimeError):
    pass


class DriveNotConfigured(DriveError):
    pass


class DriveNotConnected(DriveError):
    pass


# ------------------------------------------------------------------ credenciales

def load_client(settings: Settings) -> dict:
    if not settings.drive_configured:
        raise DriveNotConfigured("Drive no configurado: falta client_secret.json (TRAMA_DRIVE_CLIENT_FILE)")
    data = json.loads(Path(settings.drive_client_file).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    for key in ("installed", "web"):
        if key in data:
            data = data[key]
            break
    if "client_id" not in data or "client_secret" not in data:
        raise DriveNotConfigured("client_secret.json no tiene client_id/client_secret")
    return data


def load_token(settings: Settings) -> dict | None:
    path = settings.drive_token_file
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_token(settings: Settings, token: dict) -> None:
    settings.drive_dir.mkdir(parents=True, exist_ok=True)
    settings.drive_token_file.write_text(json.dumps(token, indent=2), encoding="utf-8")
    try:
        os.chmod(settings.drive_token_file, 0o600)
    except OSError:
        pass


def forget_token(settings: Settings) -> None:
    settings.drive_token_file.unlink(missing_ok=True)


def redirect_uri(settings: Settings) -> str:
    return settings.drive_redirect_uri or f"http://{settings.host}:{settings.port}/api/drive/auth/callback"


def build_auth_url(settings: Settings, state: str, code_verifier: str) -> str:
    client = load_client(settings)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.drive_auth_base}?{urlencode(params)}"


def new_pkce() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(48)


def exchange_code(settings: Settings, code: str, code_verifier: str, transport: httpx.BaseTransport | None = None) -> dict:
    client = load_client(settings)
    with httpx.Client(transport=transport, timeout=30) as http:
        r = http.post(f"{settings.drive_oauth_base}/token", data={
            "client_id": client["client_id"], "client_secret": client["client_secret"], "code": code,
            "code_verifier": code_verifier, "grant_type": "authorization_code", "redirect_uri": redirect_uri(settings),
        })
    if r.status_code != 200:
        raise DriveError(f"Intercambio de código rechazado: {r.text[:200]}")
    token = r.json()
    if "refresh_token" not in token:
        raise DriveError("Google no devolvió refresh_token; revoca el acceso en tu cuenta y vuelve a conectar")
    token["obtained_at"] = int(time.time())
    save_token(settings, token)
    return token


# ------------------------------------------------------------------ cliente

class DriveClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = load_client(settings)
        self.token = load_token(settings)
        if not self.token:
            raise DriveNotConnected("Drive no conectado: completa la autorización desde la interfaz")
        self.http = httpx.Client(transport=transport, timeout=httpx.Timeout(60, read=300))

    def close(self) -> None:
        self.http.close()

    # --- token
    def _access_token(self) -> str:
        expires_at = self.token.get("obtained_at", 0) + int(self.token.get("expires_in", 3600)) - 60
        if time.time() >= expires_at:
            r = self.http.post(f"{self.settings.drive_oauth_base}/token", data={
                "client_id": self.client["client_id"], "client_secret": self.client["client_secret"],
                "refresh_token": self.token["refresh_token"], "grant_type": "refresh_token",
            })
            if r.status_code != 200:
                raise DriveNotConnected(f"No se pudo renovar el acceso a Drive ({r.status_code}); vuelve a conectar")
            fresh = r.json()
            self.token.update({"access_token": fresh["access_token"], "expires_in": fresh.get("expires_in", 3600), "obtained_at": int(time.time())})
            save_token(self.settings, self.token)
        return self.token["access_token"]

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._access_token()}"}
        if extra:
            h.update(extra)
        return h

    def _api(self, method: str, path: str, **kw) -> httpx.Response:
        url = f"{self.settings.drive_api_base}{path}"
        for attempt in range(4):
            r = self.http.request(method, url, headers=self._headers(kw.pop("headers", None)), **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(0.5 * (2 ** attempt))
                continue
            return r
        return r

    # --- cuenta y carpeta
    def about(self) -> dict:
        r = self._api("GET", "/drive/v3/about", params={"fields": "user(emailAddress,displayName),storageQuota(limit,usage)"})
        if r.status_code != 200:
            raise DriveError(f"about: {r.status_code} {r.text[:200]}")
        return r.json()

    def ensure_folder(self) -> str:
        name = self.settings.drive_folder_name
        if self.token.get("folder_id"):
            r = self._api("GET", f"/drive/v3/files/{self.token['folder_id']}", params={"fields": "id,trashed"})
            if r.status_code == 200 and not r.json().get("trashed"):
                return self.token["folder_id"]
        q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and 'root' in parents"
        r = self._api("GET", "/drive/v3/files", params={"q": q, "fields": "files(id,name)", "spaces": "drive"})
        files = r.json().get("files", []) if r.status_code == 200 else []
        if files:
            folder_id = files[0]["id"]
        else:
            r = self._api("POST", "/drive/v3/files", json={"name": name, "mimeType": "application/vnd.google-apps.folder"}, params={"fields": "id"})
            if r.status_code != 200:
                raise DriveError(f"No se pudo crear la carpeta {name}: {r.status_code} {r.text[:200]}")
            folder_id = r.json()["id"]
        self.token["folder_id"] = folder_id
        save_token(self.settings, self.token)
        return folder_id

    def ensure_subfolder(self, name: str, parent_id: str) -> str:
        """Subcarpeta dentro de la carpeta TRAMA (creada por la app, visible con drive.file)."""
        cache = self.token.setdefault("subfolders", {})
        key = f"{parent_id}/{name}"
        if cache.get(key):
            r = self._api("GET", f"/drive/v3/files/{cache[key]}", params={"fields": "id,trashed"})
            if r.status_code == 200 and not r.json().get("trashed"):
                return cache[key]
        safe = name.replace("'", "\\'")
        q = f"name = '{safe}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and '{parent_id}' in parents"
        r = self._api("GET", "/drive/v3/files", params={"q": q, "fields": "files(id,name)", "spaces": "drive"})
        files = r.json().get("files", []) if r.status_code == 200 else []
        if files:
            folder_id = files[0]["id"]
        else:
            r = self._api("POST", "/drive/v3/files", json={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}, params={"fields": "id"})
            if r.status_code != 200:
                raise DriveError(f"No se pudo crear la subcarpeta {name}: {r.status_code} {r.text[:200]}")
            folder_id = r.json()["id"]
        cache[key] = folder_id
        save_token(self.settings, self.token)
        return folder_id

    # --- subida reanudable
    def start_upload(self, name: str, size: int, mime: str, folder_id: str, app_properties: dict | None = None) -> str:
        meta = {"name": name, "parents": [folder_id]}
        if app_properties:
            meta["appProperties"] = app_properties
        r = self._api(
            "POST", "/upload/drive/v3/files", params={"uploadType": "resumable", "fields": "id,md5Checksum,size"},
            headers={"X-Upload-Content-Type": mime, "X-Upload-Content-Length": str(size), "Content-Type": "application/json; charset=UTF-8"},
            content=json.dumps(meta),
        )
        if r.status_code != 200 or "Location" not in r.headers:
            raise DriveError(f"No se pudo iniciar la subida reanudable: {r.status_code} {r.text[:200]}")
        return r.headers["Location"]

    def upload_status(self, session_uri: str, size: int) -> int:
        """Bytes ya recibidos por Drive en esta sesión (para reanudar)."""
        r = self.http.put(session_uri, headers=self._headers({"Content-Range": f"bytes */{size}", "Content-Length": "0"}))
        if r.status_code in (200, 201):
            return size
        if r.status_code == 308:
            rng = r.headers.get("Range")
            if not rng:
                return 0
            return int(rng.split("-")[1]) + 1
        if r.status_code == 404:
            raise DriveError("La sesión de subida caducó; hay que empezar de nuevo")
        raise DriveError(f"Estado de subida desconocido: {r.status_code}")

    def upload_file(
        self, path: Path, session_uri: str, size: int, offset: int, on_progress: Callable[[int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> dict:
        """Envía desde `offset` en trozos; devuelve los metadatos finales (id, md5Checksum, size)."""
        chunk = self.settings.drive_chunk_bytes
        with open(path, "rb") as fh:
            fh.seek(offset)
            while offset < size:
                data = fh.read(chunk)
                end = offset + len(data) - 1
                r = self.http.put(session_uri, content=data, headers=self._headers({"Content-Range": f"bytes {offset}-{end}/{size}", "Content-Length": str(len(data))}))
                if r.status_code == 308:
                    rng = r.headers.get("Range")
                    offset = int(rng.split("-")[1]) + 1 if rng else end + 1
                    fh.seek(offset)
                elif r.status_code in (200, 201):
                    offset = size
                    result = r.json()
                    if on_progress:
                        on_progress(size)
                    return result
                elif r.status_code in (500, 502, 503, 504):
                    # Interrupción: consultar dónde se quedó y continuar desde ahí.
                    time.sleep(0.5)
                    offset = self.upload_status(session_uri, size)
                    fh.seek(offset)
                else:
                    raise DriveError(f"Subida rechazada: {r.status_code} {r.text[:200]}")
                if on_progress:
                    on_progress(offset)
                if should_cancel and should_cancel():
                    raise DriveError("Subida cancelada")
        r = self.http.put(session_uri, headers=self._headers({"Content-Range": f"bytes */{size}", "Content-Length": "0"}))
        if r.status_code in (200, 201):
            return r.json()
        raise DriveError(f"La subida terminó sin confirmación: {r.status_code}")

    # --- metadatos y descarga
    def get_file(self, file_id: str) -> dict | None:
        r = self._api("GET", f"/drive/v3/files/{file_id}", params={"fields": "id,name,size,md5Checksum,trashed"})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise DriveError(f"files.get: {r.status_code}")
        return r.json()

    def stream_file(self, file_id: str, range_header: str | None = None) -> tuple[int, dict, Iterator[bytes]]:
        headers = {"Range": range_header} if range_header else {}
        req = self.http.build_request("GET", f"{self.settings.drive_api_base}/drive/v3/files/{file_id}", params={"alt": "media"}, headers=self._headers(headers))
        resp = self.http.send(req, stream=True)
        if resp.status_code not in (200, 206):
            resp.close()
            raise DriveError(f"Descarga rechazada: {resp.status_code}")
        passthrough = {k: v for k, v in resp.headers.items() if k.lower() in ("content-length", "content-range", "accept-ranges", "content-type")}

        def body() -> Iterator[bytes]:
            try:
                yield from resp.iter_bytes(1024 * 256)
            finally:
                resp.close()

        return resp.status_code, passthrough, body()

    def delete_file(self, file_id: str) -> None:
        r = self._api("DELETE", f"/drive/v3/files/{file_id}")
        if r.status_code not in (200, 204, 404):
            raise DriveError(f"No se pudo borrar en Drive: {r.status_code}")


class RemoteFile:
    """Archivo de Drive como objeto binario de solo lectura con `seek`: cada lectura pide por rango
    HTTP solo los bytes necesarios (con un pequeño búfer). Permite a `zipfile` abrir un ZIP que está
    solo en Drive y extraer una entrada sin descargar el ZIP completo."""

    BLOCK = 1024 * 1024
    MAX_BLOCK = 32 * 1024 * 1024  # lectura anticipada máxima en lecturas secuenciales

    def __init__(self, client: "DriveClient", file_id: str, size: int):
        self.client, self.file_id, self.size = client, file_id, size
        self.pos = 0
        self._buf_start, self._buf = 0, b""
        self._block = self.BLOCK
        self.bytes_fetched = 0
        self.requests = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self.pos, 2: self.size}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def _fetch(self, start: int, length: int) -> bytes:
        end = min(self.size, start + length) - 1
        if end < start:
            return b""
        r = self.client._api("GET", f"/drive/v3/files/{self.file_id}", params={"alt": "media"}, headers={"Range": f"bytes={start}-{end}"})
        if r.status_code not in (200, 206):
            raise DriveError(f"Lectura por rango rechazada: {r.status_code}")
        data = r.content if r.status_code == 206 else r.content[start:end + 1]
        self.bytes_fetched += len(data)
        self.requests += 1
        return data

    def read(self, n: int = -1) -> bytes:
        if self.pos >= self.size:
            return b""
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        out = bytearray()
        off = self.pos - self._buf_start
        if 0 <= off < len(self._buf):
            # Primero lo que ya está en el búfer; nunca se vuelve a pedir.
            chunk = self._buf[off:off + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
            sequential = True
        else:
            sequential = bool(self._buf) and off == len(self._buf)
        if n > 0:
            # Lectura secuencial: el bloque se dobla hasta MAX_BLOCK, así una entrada grande viaja en
            # pocas peticiones. Un salto (índice, cabeceras locales) vuelve a 1 MB.
            self._block = min(self._block * 2, self.MAX_BLOCK) if sequential else self.BLOCK
            self._buf_start, self._buf = self.pos, self._fetch(self.pos, max(n, self._block))
            chunk = self._buf[:n]
            out += chunk
            self.pos += len(chunk)
        return bytes(out)

    def close(self) -> None:
        self.client.close()


def md5_of(path: Path, on_bytes: Callable[[int], None] | None = None) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    return h.hexdigest()


def mime_for(ext: str) -> str:
    import mimetypes

    return mimetypes.guess_type("x" + ext)[0] or "application/octet-stream"
