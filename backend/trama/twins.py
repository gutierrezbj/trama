"""Huella visual: encuentra el mismo recurso en otro archivo (otro formato, resolución o pack).

La identidad por bytes (SHA-256 / crc32) solo junta archivos idénticos. Aquí se compara lo que se
ve en la miniatura: el mismo light leak en .mov 4K y en .mp4 HD da dos archivos distintos pero la
misma imagen. No se fusiona nada: las parejas se muestran como «posibles versiones» y decide el
propietario.

Medido en la biblioteca real (6.652 miniaturas): con la huella de bits sola, letras distintas sobre
fondo negro y cualquier PNG sobre el damero de la transparencia «se parecían» (28.905 parejas);
tapando el damero y midiendo la diferencia relativa al contenido quedan ~530, con las de distinto
formato casi todas el mismo efecto.
"""
from __future__ import annotations

import collections
from pathlib import Path

from PIL import Image

from .db import Database, now_iso
from .media import CHECKER_COLORS

HASH_BITS = 256          # dHash 17×16
MAX_HAMMING = 20         # candidatos
MAX_RELATIVE_DIFF = 0.10  # diferencia relativa al contenido (32×32 gris)
MIN_STD = 6.0            # por debajo, imagen plana (negra, blanca): no se compara
BAND_BITS = 8
BUCKET_CAP = 600         # cubetas enormes = imágenes casi iguales en esa franja por ser planas


def visual_print(thumb: Path) -> dict:
    """Huella de una miniatura: dHash de 256 bits y 32×32 en gris, con el damero pintado de negro."""
    with Image.open(thumb) as im:
        rgb = im.convert("RGB")
    w, h = rgb.size
    small = rgb.resize((min(w, 160), min(h, 160)))
    px = small.load()
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            r, g, b = px[x, y]
            if any(abs(r - c[0]) < 10 and abs(g - c[1]) < 10 and abs(b - c[2]) < 10 for c in CHECKER_COLORS):
                px[x, y] = (0, 0, 0)
    gray = small.convert("L")
    d = list(gray.resize((17, 16)).getdata())
    bits = 0
    for y in range(16):
        for x in range(16):
            bits = (bits << 1) | (d[y * 17 + x] > d[y * 17 + x + 1])
    tiny = bytes(gray.resize((32, 32)).getdata())
    mean = sum(tiny) / 1024
    std = (sum((p - mean) ** 2 for p in tiny) / 1024) ** 0.5
    return {"dhash": f"{bits:064x}", "tiny": tiny, "flat": std < MIN_STD}


def store_print(db: Database, version_id: str, thumb: Path) -> None:
    v = db.one("SELECT media_kind, analysis FROM asset_versions WHERE id = ?", (version_id,))
    if v is None:
        return
    from .db import loads

    a = loads(v["analysis"], {})
    visual = a.get("video") or a.get("image") or {}
    w, h = visual.get("width") or 0, visual.get("height") or 0
    try:
        p = visual_print(thumb)
    except Exception:
        p = {"dhash": None, "tiny": None, "flat": True}
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO vprints(version_id, dhash, tiny, flat, aspect, duration, media_kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, p["dhash"], p["tiny"], int(p["flat"]), (w / h) if w and h else None, a.get("duration_s"), v["media_kind"], now_iso()),
        )


def _similar(a, b) -> float | None:
    """Diferencia relativa (0 = iguales) si son la misma imagen; None si no."""
    if a["media_kind"] != b["media_kind"]:
        return None
    if a["aspect"] and b["aspect"] and abs(a["aspect"] - b["aspect"]) > 0.03 * max(a["aspect"], b["aspect"]):
        return None
    if a["media_kind"] == "video":
        if a["duration"] is None or b["duration"] is None:
            return None
        if abs(a["duration"] - b["duration"]) > max(0.15, 0.03 * max(a["duration"], b["duration"])):
            return None
    if bin(a["bits"] ^ b["bits"]).count("1") > MAX_HAMMING:
        return None
    num = sum(abs(p - q) for p, q in zip(a["tiny"], b["tiny"]))
    den = sum(max(p, q) for p, q in zip(a["tiny"], b["tiny"])) + 1
    diff = num / den
    return diff if diff <= MAX_RELATIVE_DIFF else None


def rebuild_twins(db: Database) -> int:
    """Recalcula todas las parejas de posibles versiones. Devuelve cuántas hay."""
    rows = db.query(
        "SELECT p.version_id, p.dhash, p.tiny, p.aspect, p.duration, p.media_kind FROM vprints p "
        "WHERE p.flat = 0 AND p.dhash IS NOT NULL AND EXISTS (SELECT 1 FROM assets a WHERE a.version_id = p.version_id AND a.duplicate_of IS NULL)"
    )
    items = [{**dict(r), "bits": int(r["dhash"], 16)} for r in rows]
    bands: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for i, it in enumerate(items):
        for b in range(HASH_BITS // BAND_BITS):
            bands[(b, (it["bits"] >> (b * BAND_BITS)) & 0xFF)].append(i)
    pairs: dict[tuple[str, str], float] = {}
    seen: set[tuple[int, int]] = set()
    for idx in bands.values():
        if len(idx) > BUCKET_CAP:
            continue
        for x in range(len(idx)):
            for y in range(x + 1, len(idx)):
                key = (idx[x], idx[y])
                if key in seen:
                    continue
                seen.add(key)
                a, b = items[idx[x]], items[idx[y]]
                diff = _similar(a, b)
                if diff is not None:
                    va, vb = sorted((a["version_id"], b["version_id"]))
                    pairs[(va, vb)] = round(diff, 4)
    with db.tx() as conn:
        conn.execute("DELETE FROM visual_twins")
        conn.executemany("INSERT INTO visual_twins(a, b, diff) VALUES (?, ?, ?)", [(a, b, d) for (a, b), d in pairs.items()])
    return len(pairs)


def twins_of(db: Database, version_id: str) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT CASE WHEN a = ? THEN b ELSE a END AS version_id, diff FROM visual_twins WHERE a = ? OR b = ? ORDER BY diff",
        (version_id, version_id, version_id),
    )]
