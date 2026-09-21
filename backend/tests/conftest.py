"""Fixtures: catálogo temporal, raíz permitida con archivos reales generados con FFmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trama.api import create_app
from trama.config import Settings
from trama.db import Database
from trama.media import Tools, resolve_tools


@pytest.fixture(scope="session")
def tools() -> Tools:
    settings = Settings(data_dir=Path("."), allowed_roots=[])
    try:
        return resolve_tools(settings)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"FFmpeg no disponible: {exc}")


def make_fixture_files(tools: Tools, folder: Path) -> dict[str, Path]:
    """Genera archivos sintéticos (etiquetados como tales) para probar el pipeline sin depender
    de las muestras privadas. No sustituyen a las muestras verificadas."""
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    # vídeo opaco 2 s
    files["opaque"] = folder / "Transiciones" / "test_opaque.mp4"
    files["opaque"].parent.mkdir(exist_ok=True)
    subprocess.run([tools.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=2",
                    "-pix_fmt", "yuv420p", str(files["opaque"])], check=True)
    # vídeo con alfa real (ProRes 4444) 1 s, vertical
    files["alpha"] = folder / "VFX" / "test_alpha.mov"
    files["alpha"].parent.mkdir(exist_ok=True)
    subprocess.run([tools.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red@0.5:s=180x320:r=25:d=1,format=rgba",
                    "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", str(files["alpha"])], check=True)
    # audio wav 1 s
    files["audio"] = folder / "Audio" / "test_tone.wav"
    files["audio"].parent.mkdir(exist_ok=True)
    subprocess.run([tools.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "pcm_s16le", str(files["audio"])], check=True)
    # archivo corrupto con extensión de vídeo
    files["broken"] = folder / "roto.mp4"
    files["broken"].write_bytes(b"esto no es un mp4")
    return files


@pytest.fixture
def env(tmp_path: Path, tools: Tools):
    root = tmp_path / "raiz"
    files = make_fixture_files(tools, root)
    data_dir = tmp_path / "datos"
    settings = Settings(data_dir=data_dir, allowed_roots=[root], workers=2, ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe)
    app = create_app(settings, start_worker=True)
    client = TestClient(app)
    client.__enter__()
    state = app.state.trama
    yield {"client": client, "settings": settings, "root": root, "files": files, "state": state, "tmp": tmp_path}
    client.__exit__(None, None, None)
    state.db.close()


def wait_idle(client: TestClient, timeout: float = 120.0) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get("/api/jobs/summary").json()["totals"]
        if not s.get("queued") and not s.get("running"):
            return
        time.sleep(0.25)
    raise AssertionError("El worker no terminó a tiempo")


def source_id(client: TestClient) -> str:
    return client.get("/api/fs/sources").json()[0]["id"]


def import_all(client: TestClient, path: str = "") -> dict:
    imp = client.post("/api/imports", json={"source_id": source_id(client), "path": path}).json()
    wait_idle(client)
    return client.get(f"/api/imports/{imp['id']}").json()


def reopen(env: dict) -> TestClient:
    """Simula un reinicio: nuevo proceso de app sobre el mismo directorio de datos."""
    env["client"].__exit__(None, None, None)
    env["state"].db.close()
    app = create_app(env["settings"], start_worker=True)
    client = TestClient(app)
    client.__enter__()
    env["client"] = client
    env["state"] = app.state.trama
    return client


__all__ = ["wait_idle", "source_id", "import_all", "reopen", "make_fixture_files"]
