"""Índice del «trastero»: catálogos externos que el propietario tiene comprados o suscritos (p. ej.
el área de miembros de un pack) y que no se descargan. Se guarda solo la ficha de cada paquete
(nombre, categoría, tamaño, portada y página) para que, al buscar en TRAMA, aparezca también
«esto lo tienes allí» con su enlace. Opcionalmente la IA de visión lee la portada y le pone
descripción y etiquetas.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .db import Database, loads, new_id, normalize_text, now_iso
from .tags import compute_auto_tags, search_text_for

_UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def parse_size(text: str | None) -> int | None:
    m = re.match(r"\s*([\d.,]+)\s*(KB|MB|GB|TB)", text or "", re.I)
    if not m:
        return None
    return int(float(m.group(1).replace(",", ".")) * _UNITS[m.group(2).upper()])


def _search_text(name: str, category: str, description: str, tags: list[str]) -> str:
    auto = compute_auto_tags(f"{category}/{name}", "video", "", {})
    return search_text_for(name, "", description, tags, auto, category)


def import_items(db: Database, source: str, items: list[dict]) -> dict:
    """Alta o actualización de las fichas de un catálogo externo. `items`: name, category, size,
    page_url, cover_url. Lo que ya no aparece en el catálogo se borra."""
    now = now_iso()
    seen: set[str] = set()
    added = updated = 0
    with db.tx() as conn:
        for it in items:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            seen.add(name)
            row = conn.execute("SELECT id, tags, description FROM external_items WHERE source = ? AND name = ?", (source, name)).fetchone()
            tags = loads(row["tags"], []) if row else []
            desc = row["description"] if row else ""
            values = (it.get("category") or "", parse_size(it.get("size")), it.get("page_url") or "", it.get("cover_url") or "",
                      _search_text(name, it.get("category") or "", desc, tags), now)
            if row:
                conn.execute("UPDATE external_items SET category = ?, size_bytes = ?, page_url = ?, cover_url = ?, search_text = ?, updated_at = ? WHERE id = ?", (*values, row["id"]))
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO external_items(id, source, name, category, size_bytes, page_url, cover_url, search_text, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("ext"), source, name, *values),
                )
                added += 1
        gone = [r["id"] for r in conn.execute("SELECT id, name FROM external_items WHERE source = ?", (source,)).fetchall() if r["name"] not in seen]
        for gid in gone:
            conn.execute("DELETE FROM external_items WHERE id = ?", (gid,))
    return {"added": added, "updated": updated, "removed": len(gone)}


def search(db: Database, q: str, limit: int = 8) -> dict:
    terms = normalize_text(q).split()
    if not terms:
        return {"total": 0, "items": []}
    where = " AND ".join("(' ' || search_text || ' ') LIKE ?" for _ in terms)
    params = [f"% {t}%" for t in terms]
    total = db.one(f"SELECT COUNT(*) AS n FROM external_items WHERE {where}", params)["n"]
    rows = db.query(f"SELECT * FROM external_items WHERE {where} ORDER BY size_bytes IS NULL, name LIMIT ?", params + [limit])
    return {"total": total, "items": [
        {"id": r["id"], "source": r["source"], "name": r["name"], "category": r["category"], "size_bytes": r["size_bytes"],
         "page_url": r["page_url"], "cover_url": r["cover_url"], "description": r["description"], "tags": loads(r["tags"], [])}
        for r in rows
    ]}


def describe_covers(db: Database, settings, model: str = "openai:gpt-6-luna", limit: int | None = None) -> dict:
    """La IA lee la portada de cada paquete sin descripción (suelen llevar escrito qué contienen)."""
    import httpx

    from .vision import describe

    rows = db.query("SELECT * FROM external_items WHERE description = '' AND cover_url <> ''" + (f" LIMIT {int(limit)}" if limit else ""))
    folder = settings.data_dir / "ia" / "portadas"
    folder.mkdir(parents=True, exist_ok=True)
    done = errors = 0
    cost = 0.0
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        for r in rows:
            try:
                img = folder / f"{r['id']}.jpg"
                if not img.exists():
                    resp = http.get(r["cover_url"])
                    resp.raise_for_status()
                    from PIL import Image
                    import io

                    with Image.open(io.BytesIO(resp.content)) as im:
                        im = im.convert("RGB")
                        im.thumbnail((768, 768))
                        im.save(img, "JPEG", quality=85)
                hints = f"product cover of a downloadable pack titled «{r['name']}», category {r['category']}; describe what the pack contains, not the cover design"
                res = describe(settings, model, img, hints, http, what="still")
                cost += res.get("cost_usd", 0)
                with db.tx() as conn:
                    conn.execute("UPDATE external_items SET description = ?, tags = ?, search_text = ? WHERE id = ?",
                                 (res["description"], json.dumps(res["tags"], ensure_ascii=False),
                                  _search_text(r["name"], r["category"], res["description"], res["tags"]), r["id"]))
                done += 1
            except Exception:
                errors += 1
    return {"done": done, "errors": errors, "cost_usd": round(cost, 4)}
