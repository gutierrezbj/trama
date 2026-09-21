"""Simulador local de Google Drive para demostrar E3 sin cuenta de Google.

Implementa lo que usa TRAMA: pantalla de autorización OAuth (redirige al instante), token,
about, carpeta, subida reanudable (con UNA interrupción 503 a mitad para mostrar la reanudación),
metadatos, descarga con rangos y borrado. Todo en memoria; nada sale del equipo.

Uso (dos terminales):
  1) python scripts\drive_simulado.py            # escucha en http://127.0.0.1:8799
  2) en .env de TRAMA, temporalmente:
       TRAMA_DRIVE_CLIENT_FILE=<ruta>\client_secret_simulado.json   (lo crea este script)
       TRAMA_DRIVE_API_BASE=http://127.0.0.1:8799
       TRAMA_DRIVE_OAUTH_BASE=http://127.0.0.1:8799
       TRAMA_DRIVE_AUTH_BASE=http://127.0.0.1:8799/o/oauth2/v2/auth
     y reiniciar `scripts\serve.cmd`. En «Copias y Drive» → Conectar.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Drive simulado")
FILES: dict[str, dict] = {}
SESSIONS: dict[str, dict] = {}
STATE = {"n": 0, "fail_next_chunk": True, "chunk_delay": 0.35}


def _nid(prefix: str) -> str:
    STATE["n"] += 1
    return f"{prefix}{STATE['n']}"


@app.get("/o/oauth2/v2/auth", response_class=HTMLResponse)
def auth_page(redirect_uri: str, state: str, scope: str = "", client_id: str = ""):
    return f"""<!doctype html><meta charset=utf-8><title>Drive simulado · autorizar</title>
    <body style="font-family:sans-serif;background:#141618;color:#f2f0e9;display:grid;place-items:center;height:100vh;margin:0">
    <div style="max-width:460px;padding:28px;border:1px solid #333;border-radius:16px;background:#202428">
    <h2 style="margin:0 0 8px">Drive <span style="color:#e8be46">SIMULADO</span></h2>
    <p>Esto no es Google. Es un simulador local para la demostración de E3.</p>
    <p style="color:#a6adb4;font-size:13px">Cliente: <code>{client_id}</code><br>Alcance solicitado: <code>{scope}</code></p>
    <a href="{redirect_uri}?state={state}&code=codigo-ok" style="display:inline-block;padding:12px 18px;background:#e8be46;color:#1b1608;border-radius:12px;text-decoration:none;font-weight:600">Autorizar a TRAMA</a>
    </div></body>"""


@app.post("/token")
async def token(request: Request):
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    if form.get("grant_type") == "authorization_code":
        if form.get("code") != "codigo-ok" or not form.get("code_verifier"):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return {"access_token": "sim-access-1", "refresh_token": "sim-refresh", "expires_in": 3600, "token_type": "Bearer"}
    return {"access_token": f"sim-access-{STATE['n']}", "expires_in": 3600, "token_type": "Bearer"}


def _auth(request: Request) -> Response | None:
    if not request.headers.get("authorization", "").startswith("Bearer "):
        return JSONResponse({"error": "sin token"}, status_code=401)
    return None


@app.get("/drive/v3/about")
def about(request: Request):
    if (e := _auth(request)):
        return e
    usage = sum(len(f.get("data", b"")) for f in FILES.values())
    return {"user": {"emailAddress": "simulador@drive.local", "displayName": "Drive simulado"}, "storageQuota": {"usage": str(usage), "limit": str(15 * 1024**3)}}


@app.get("/drive/v3/files")
def list_files(request: Request, q: str = ""):
    if (e := _auth(request)):
        return e
    folders = [{"id": f["id"], "name": f["name"]} for f in FILES.values() if f.get("mimeType") == "application/vnd.google-apps.folder"]
    return {"files": folders}


@app.post("/drive/v3/files")
async def create_file(request: Request):
    if (e := _auth(request)):
        return e
    meta = await request.json()
    fid = _nid("carpeta")
    FILES[fid] = {"id": fid, "name": meta["name"], "mimeType": meta.get("mimeType"), "trashed": False}
    return {"id": fid}


@app.post("/upload/drive/v3/files")
async def start_upload(request: Request):
    if (e := _auth(request)):
        return e
    meta = json.loads(await request.body())
    sid = _nid("sesion")
    SESSIONS[sid] = {"meta": meta, "size": int(request.headers["x-upload-content-length"]), "data": bytearray()}
    return Response(status_code=200, headers={"Location": f"http://127.0.0.1:8799/subida/{sid}"})


def _finish(sess: dict) -> dict:
    fid = _nid("archivo")
    data = bytes(sess["data"])
    FILES[fid] = {"id": fid, "name": sess["meta"]["name"], "size": str(len(data)), "md5Checksum": hashlib.md5(data).hexdigest(), "trashed": False, "data": data, "appProperties": sess["meta"].get("appProperties")}
    print(f"  OK {sess['meta']['name']}: {len(data)} bytes, md5 {FILES[fid]['md5Checksum'][:12]}...", flush=True)
    return {"id": fid, "md5Checksum": FILES[fid]["md5Checksum"], "size": str(len(data))}


@app.put("/subida/{sid}")
async def upload_chunk(sid: str, request: Request):
    sess = SESSIONS.get(sid)
    if sess is None:
        return JSONResponse({"error": "sesión caducada"}, status_code=404)
    m = re.match(r"bytes (\*|(\d+)-(\d+))/(\d+)", request.headers.get("content-range", ""))
    if m is None:
        return JSONResponse({"error": "Content-Range"}, status_code=400)
    if m.group(1) == "*":
        if len(sess["data"]) >= sess["size"]:
            return _finish(sess)
        return Response(status_code=308, headers={"Range": f"bytes=0-{len(sess['data']) - 1}"} if sess["data"] else {})
    start = int(m.group(2))
    body = await request.body()
    time.sleep(STATE["chunk_delay"])  # para que el progreso se vea en la interfaz
    if STATE["fail_next_chunk"] and start > 0:
        STATE["fail_next_chunk"] = False
        half = body[: len(body) // 2]
        sess["data"][start:start + len(half)] = half
        del sess["data"][start + len(half):]
        print(f"  X interrupción simulada en el byte {start + len(half)} (503); TRAMA debe reanudar", flush=True)
        return Response(status_code=503)
    if start != len(sess["data"]):
        return JSONResponse({"error": f"trozo fuera de orden {start} != {len(sess['data'])}"}, status_code=400)
    sess["data"] += body
    if len(sess["data"]) >= sess["size"]:
        return _finish(sess)
    return Response(status_code=308, headers={"Range": f"bytes=0-{len(sess['data']) - 1}"})


@app.get("/drive/v3/files/{fid}")
def get_file(fid: str, request: Request, alt: str = ""):
    if (e := _auth(request)):
        return e
    f = FILES.get(fid)
    if f is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if alt == "media":
        data = f["data"]
        rng = request.headers.get("range")
        if rng:
            a, b = rng.replace("bytes=", "").split("-")
            a, b = int(a), int(b) if b else len(data) - 1
            return Response(content=data[a:b + 1], status_code=206, headers={"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"}, media_type="application/octet-stream")
        return Response(content=data, headers={"Accept-Ranges": "bytes"}, media_type="application/octet-stream")
    return {k: v for k, v in f.items() if k != "data"}


@app.delete("/drive/v3/files/{fid}")
def delete_file(fid: str, request: Request):
    if (e := _auth(request)):
        return e
    FILES.pop(fid, None)
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def index():
    rows = "".join(f"<li>{f['name']} — {f.get('size', '-')} bytes — md5 {f.get('md5Checksum', '-')}</li>" for f in FILES.values() if "data" in f)
    return f"<meta charset=utf-8><body style='font-family:sans-serif;background:#141618;color:#f2f0e9;padding:24px'><h2>Drive <span style='color:#e8be46'>SIMULADO</span> · archivos recibidos</h2><ul>{rows or '<li>ninguno</li>'}</ul></body>"


if __name__ == "__main__":
    import uvicorn

    secret = Path(__file__).resolve().parent / "client_secret_simulado.json"
    secret.write_text(json.dumps({"installed": {"client_id": "simulado", "client_secret": "simulado"}}), encoding="utf-8")
    print(f"Drive simulado en http://127.0.0.1:8799  (client_secret: {secret})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8799, log_level="warning")
