"""Nivel 2: IA de visión para lo que las carpetas no dicen (qué se ve, cómo se mueve).

Cada recurso se resume en una hoja de 3 fotogramas (20 %, 50 % y 80 % del clip, sacados de la
vista previa ya generada: nada se descarga del pack) y se envía a uno o varios modelos compatibles
con la API de OpenAI: OpenAI de pago o un modelo local gratis (LM Studio en el Mac).

La prueba (`ai_test`) pasa la misma muestra por varios modelos para compararlos con coste y tiempo
medidos, antes de gastar nada en toda la biblioteca.
"""
from __future__ import annotations

import base64
import io
import json
import random
import re
import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image

from .config import Settings
from .db import Database, loads, new_id, now_iso

# Dólares por millón de tokens (entrada, salida), tarifa estándar de OpenAI a 28 sep 2026.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
}
# Modelos que razonan antes de responder: sin razonamiento la respuesta no se queda vacía por
# agotar el presupuesto de tokens (pasó con gpt-6-luna en 14 de 50) y sale más barata.
NO_REASONING = {"gpt-6-luna", "gpt-5.4-mini", "gpt-5.4-nano"}
DEFAULT_TEST_MODELS = ["local:qwen/qwen3-vl-8b", "openai:gpt-6-luna", "openai:gpt-5.4-mini"]

PROMPT = """You are cataloguing a stock asset for a video editor (VFX, overlays, transitions, titles, textures).
{what}; a grey checkerboard means transparency (alpha), not content.
Hints from the pack folders (may be incomplete): {hints}

Reply ONLY with JSON:
{{"description": "<one short sentence in Spanish describing what is seen{motion}>",
  "tags": ["<3 to 8 lowercase English terms an editor would search, e.g. smoke, light leak, paper burn, glitch, lens flare, sparks, countdown, lower third; no generic words like video, effect, frame, checkerboard, transparent>"]}}"""


# Qué se le enseña al modelo. Con una imagen fija no hay movimiento que describir: decirle «3
# fotogramas» le hacía inventarlo (visto en la primera prueba).
WHAT = {
    "video3": ("The image shows 3 frames of the clip side by side (start, middle, end)", " and how it moves or changes"),
    "video1": ("The image is a single frame of a video clip", ""),
    "still": ("The image is a still graphic (not a video): do not describe or invent any motion", ""),
}


def sheet_what(db: Database, version_id: str) -> str:
    """video3 si hay vista previa de vídeo (hoja de 3 fotogramas), video1 si solo miniatura, still si es imagen."""
    v = db.one("SELECT media_kind FROM asset_versions WHERE id = ?", (version_id,))
    if not v or v["media_kind"] != "video":
        return "still"
    proxy = db.one("SELECT 1 FROM derivatives WHERE version_id = ? AND status = 'ready' AND kind IN ('proxy','proxy_checker','proxy_dark')", (version_id,))
    return "video3" if proxy else "video1"


class VisionError(RuntimeError):
    pass


def contact_sheet(settings: Settings, db: Database, version_id: str, dest: Path) -> Path:
    """Hoja de 3 fotogramas desde la vista previa (vídeo) o la miniatura (imagen)."""
    if dest.exists():
        return dest
    rows = {r["kind"]: r["rel_path"] for r in db.query("SELECT kind, rel_path FROM derivatives WHERE version_id = ? AND status = 'ready'", (version_id,))}
    version = db.one("SELECT media_kind, analysis FROM asset_versions WHERE id = ?", (version_id,))
    dest.parent.mkdir(parents=True, exist_ok=True)
    proxy = rows.get("proxy") or rows.get("proxy_checker") or rows.get("proxy_dark")
    if version and version["media_kind"] == "video" and proxy:
        from .media import resolve_tools

        ffmpeg = resolve_tools(settings).ffmpeg
        duration = float(loads(version["analysis"], {}).get("duration_s") or 1.0)
        frames = []
        for share in (0.2, 0.5, 0.8):
            out = subprocess.run(
                [ffmpeg, "-v", "error", "-ss", f"{duration * share:.3f}", "-i", str(settings.derivatives_dir / proxy),
                 "-frames:v", "1", "-vf", "scale=320:-2", "-f", "image2pipe", "-c:v", "png", "-"],
                capture_output=True, timeout=60,
            )
            if out.returncode == 0 and out.stdout:
                frames.append(Image.open(io.BytesIO(out.stdout)).convert("RGB"))
        if frames:
            h = max(f.height for f in frames)
            sheet = Image.new("RGB", (sum(f.width for f in frames) + 8 * (len(frames) - 1), h), (20, 20, 20))
            x = 0
            for f in frames:
                sheet.paste(f, (x, 0))
                x += f.width + 8
            sheet.save(dest, "JPEG", quality=85)
            return dest
    if rows.get("thumb"):
        with Image.open(settings.derivatives_dir / rows["thumb"]) as im:
            im = im.convert("RGB")
            im.thumbnail((960, 960))
            im.save(dest, "JPEG", quality=85)
        return dest
    raise VisionError("Sin vista previa todavía")


def _endpoint(settings: Settings, model_spec: str) -> tuple[str, dict, str]:
    provider, _, model = model_spec.partition(":")
    if provider == "openai":
        if not settings.openai_api_key:
            raise VisionError("Falta TRAMA_OPENAI_API_KEY en el .env del servidor")
        return "https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {settings.openai_api_key}"}, model
    if provider == "local":
        if not settings.local_vision_url:
            raise VisionError("Falta TRAMA_LOCAL_VISION_URL (LM Studio del Mac)")
        return f"{settings.local_vision_url}/chat/completions", {}, model
    raise VisionError(f"Proveedor desconocido: {provider}")


def _parse(content: str) -> tuple[str, list[str]]:
    start = (content or "").find("{")
    if start < 0:
        raise VisionError(f"Respuesta sin JSON: {(content or '')[:120]!r}")
    data, _end = json.JSONDecoder().raw_decode(content[start:])  # ignora lo que venga después del objeto
    tags = []
    for t in data.get("tags") or []:
        t = re.sub(r"[_\-]+", " ", str(t)).strip().lower()
        if t and t not in tags and t not in {"video", "effect", "frame", "checkerboard", "transparent"}:
            tags.append(t)
    return str(data.get("description") or "").strip(), tags[:8]


def describe(settings: Settings, model_spec: str, sheet: Path, hints: str, client: httpx.Client | None = None, what: str = "video3") -> dict:
    """Llama al modelo con la hoja de fotogramas. Devuelve descripción, etiquetas, tokens, coste y tiempo."""
    url, headers, model = _endpoint(settings, model_spec)
    image = base64.b64encode(sheet.read_bytes()).decode()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(hints=hints or "none", what=WHAT[what][0], motion=WHAT[what][1])},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}", "detail": "low"}},
        ]}],
    }
    if model_spec.startswith("openai:"):
        body["max_completion_tokens"] = 600
        if model in NO_REASONING:
            body["reasoning_effort"] = "none"
    else:
        body["max_tokens"] = 300
    started = time.perf_counter()
    own = client is None
    client = client or httpx.Client(timeout=180)
    try:
        r = client.post(url, json=body, headers=headers)
    finally:
        if own:
            client.close()
    seconds = round(time.perf_counter() - started, 2)
    if r.status_code >= 400:
        raise VisionError(f"HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    description, tags = _parse(data["choices"][0]["message"].get("content") or "")
    usage = data.get("usage") or {}
    tin, tout = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    price_in, price_out = PRICES.get(model, (0.0, 0.0)) if model_spec.startswith("openai:") else (0.0, 0.0)
    return {"description": description, "tags": tags, "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round((tin * price_in + tout * price_out) / 1e6, 6), "seconds": seconds}


# ---- muestra y prueba ----------------------------------------------------------------------

VISUAL_SQL = (
    "SELECT a.version_id, a.category FROM assets a JOIN asset_versions v ON v.id = a.version_id "
    "WHERE a.duplicate_of IS NULL AND v.analysis_status = 'done' "
    "AND (v.media_kind IN ('video', 'image') OR json_extract(v.analysis, '$.preview_support') IN ('image', 'mogrt')) "
    "AND EXISTS (SELECT 1 FROM derivatives d WHERE d.version_id = v.id AND d.kind = 'thumb' AND d.status = 'ready')"
)


def pick_sample(db: Database, size: int = 50, seed: int = 7) -> list[str]:
    """Muestra variada: se reparte entre categorías (redondo) para no llenarla de letras o LUT."""
    by_cat: dict[str, list[str]] = {}
    for r in db.query(VISUAL_SQL):
        by_cat.setdefault(r["category"], []).append(r["version_id"])
    rng = random.Random(seed)
    for ids in by_cat.values():
        rng.shuffle(ids)
    picked: list[str] = []
    while len(picked) < size and any(by_cat.values()):
        for cat in sorted(by_cat):
            if by_cat[cat] and len(picked) < size:
                picked.append(by_cat[cat].pop())
    return picked


def create_test_run(db: Database, models: list[str], size: int = 50) -> str:
    run_id = new_id("air")
    sample = pick_sample(db, size)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO ai_runs(id, kind, models, sample, status, created_at) VALUES (?, 'test', ?, ?, 'queued', ?)",
            (run_id, json.dumps(models), json.dumps(sample), now_iso()),
        )
        conn.execute("INSERT INTO jobs(id, kind, status, payload, created_at) VALUES (?, 'ai_test', 'queued', ?, ?)",
                     (new_id("job"), json.dumps({"run_id": run_id}), now_iso()))
    return run_id


def hints_for(db: Database, version_id: str) -> str:
    row = db.one("SELECT title, auto_tags FROM assets WHERE version_id = ? LIMIT 1", (version_id,))
    if not row:
        return ""
    folder_tags = [t for t in loads(row["auto_tags"], []) if not t.endswith((" fps", " bpm"))]
    return f"title «{row['title']}»; tags: {', '.join(folder_tags[:10]) or 'none'}"


def sheet_path(settings: Settings, version_id: str) -> Path:
    return settings.data_dir / "ia" / "hojas" / f"{version_id}.jpg"


def create_full_run(db: Database, model: str, max_usd: float) -> str:
    """Pasada por toda la biblioteca visual con el modelo elegido y un tope de gasto."""
    run_id = new_id("air")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO ai_runs(id, kind, models, sample, status, created_at) VALUES (?, 'full', ?, '[]', 'queued', ?)",
            (run_id, json.dumps([model]), now_iso()),
        )
        conn.execute("INSERT INTO jobs(id, kind, status, payload, created_at) VALUES (?, 'ai_full', 'queued', ?, ?)",
                     (new_id("job"), json.dumps({"run_id": run_id, "model": model, "max_usd": max_usd}), now_iso()))
    return run_id


def pending_for_full(db: Database, model: str) -> list[str]:
    """Versiones visuales que aún no tienen etiquetas de este modelo."""
    return [r["version_id"] for r in db.query(
        f"SELECT x.version_id FROM ({VISUAL_SQL}) x WHERE NOT EXISTS "
        "(SELECT 1 FROM assets a2 WHERE a2.version_id = x.version_id AND a2.ai_model = ?)", (model,))]


def apply_label(db: Database, version_id: str, model: str, description: str, tags: list[str]) -> None:
    """Guarda en la ficha las etiquetas de la IA y su descripción si no hay una escrita a mano."""
    with db.tx() as conn:
        conn.execute(
            "UPDATE assets SET ai_tags = ?, ai_model = ?, "
            "description = CASE WHEN description_source IN ('none', 'inferred') THEN ? ELSE description END, "
            "description_source = CASE WHEN description_source IN ('none', 'inferred') AND ? <> '' THEN 'inferred' ELSE description_source END "
            "WHERE version_id = ?",
            (json.dumps(tags, ensure_ascii=False), model, description, description, version_id),
        )
