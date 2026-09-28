"""Etiquetas de nivel 1: deducidas de las carpetas del pack y de los datos medidos.

Sin IA y sin coste. Los packs mezclan inglés, español y portugués («Smoke», «Humo», «Fumaça»):
cada etiqueta canónica, en español, reúne sus sinónimos. Van en `assets.auto_tags`, aparte de las
etiquetas humanas, y se recalculan enteras cuando cambia el vocabulario (AUTOTAG_VERSION).
"""
from __future__ import annotations

import json
import re

from .db import Database, loads, normalize_text, now_iso

# Súbase al cambiar el vocabulario o las reglas: el arranque recalcula todo el catálogo.
AUTOTAG_VERSION = "1"

# (etiqueta, sinónimos). Los sinónimos son expresiones sobre texto normalizado (minúsculas, sin
# acentos, separadores como espacios) y se buscan como palabras completas; `\w*` alarga un prefijo.
VOCABULARY: list[tuple[str, str]] = [
    # efectos visuales
    ("humo", r"smoke\w*|humo|fumaca|fumo|vapor|steam"),
    ("fuego", r"fire|fires|fuego|fogo|flames?|llamas?"),
    ("explosión", r"explo\w*|bursts?|bombs?|blast\w*|charges?|detona\w*"),
    ("chispas", r"sparks?|chispas?|faiscas?|eletrify|electrify"),
    ("partículas", r"particles?|particulas?|particle\w*"),
    ("polvo", r"dust\w*|polvo|powder|poeira|debris|dirt\w*"),
    ("sangre", r"blood|sangre|sangue"),
    ("agua", r"water|agua|splash\w*|drops?|gotas?|liquid\w*"),
    ("lluvia", r"rain|lluvia|chuva|thunderstorm|storm"),
    ("cristal roto", r"glass|cristal|vidrio|windshields?|cracks?|shatter\w*"),
    ("disparos", r"muzzle\w*|bullet\w*|shells?|gun\w*|disparos?"),
    ("electricidad", r"electric\w*|eletric\w*|lightning|thunder|rayos?|energy"),
    ("magia", r"magic|magico|magia|fairy|shimmer|sakura"),
    ("brillo", r"glow|shine|brillo|bright\w*|prism\w*|diamonds?"),
    ("destello", r"flares?|lens flare|destellos?|flash|flashes"),
    ("fugas de luz", r"light leaks?|leaks?|luzes|luces|light transitions?"),
    ("quemado", r"film burns?|burn marks?|burn|burns|burning|quemad\w*|film damage"),
    ("película", r"film|films|filme|16mm|8mm|super 8|film leaders?|perforation|celuloide"),
    ("grano", r"grain|grano|granulado"),
    ("vhs", r"vhs|camcorder\w*|digital8"),
    ("tv antigua", r"crt|old tv|tv noise|static|analog\w*|interferenc\w*"),
    ("glitch", r"glitch\w*"),
    ("neón", r"neon|led"),
    ("hud", r"hud|huds|hologram\w*|holografic\w*|holographic|interface|visual systems|terminal"),
    ("futurista", r"futur\w*|sci fi|scifi|cyber\w*|tech|digital"),
    ("dibujado a mano", r"sketch\w*|scribble\w*|doodle\w*|hand drawn|written|garabatos?|dibujad\w*"),
    ("papel", r"paper|papel|postit|paper rip\w*|origami"),
    ("cinta adhesiva", r"scotch|duck tape|tape|cinta"),
    ("textura", r"textur\w*|marble|metal|wood|plastic|photocopy|gradient|grunge"),
    ("grunge", r"grunge"),
    ("fondo", r"backgrounds?|fondos?|backdrops?|bg"),
    ("formas", r"lines|shapes?|formas?|figuras?|abstract\w*|circles?|squares?|geometr\w*"),
    ("flechas", r"arrows?|flechas?|setas?"),
    ("emoji", r"emojis?|emoticon\w*"),
    ("manos", r"hands?|manos|maos|gestos"),
    ("redes sociales", r"social|redes|sociais|twitter|instagram|youtube|tiktok|facebook|like|dislike|subscribe|suscri\w*"),
    ("notificaciones", r"notifica\w*|notification\w*|alerts?|warning|error"),
    ("números", r"numbers?|numeros?|numerals?|counter|contador|countdown"),
    ("tipografía", r"letters?|letras?|fonts?|tipografia|typograph\w*|alphabet|upper case|lower case|characters|letter"),
    ("títulos", r"titles?|titulos?|intro|abertura"),
    ("rótulos", r"lower thirds?|tercios inferiores|rotulos?|callouts?"),
    ("marcos", r"frames?|marcos?|letterbox|aspect ratio|borders?|bordes?"),
    ("cartoon", r"cartoon\w*|comics?|comic|ballons|balloons|bocadillos?"),
    ("cumpleaños", r"cumpleanos|cumpeanos|birthday|aniversario"),
    ("dinero", r"money|dinero|dinheiro|cash|chash|cassino|casino"),
    ("retro", r"retro|vintage|old|antigu\w*"),
    ("barrido", r"wipes?|swipes?|slides?|deslizantes"),
    ("objetos", r"objects?|objetos?|objectos?"),
    ("pinceladas", r"brush\w*|pincel\w*|brochazos?|paint strokes?"),
    ("desenfoque", r"blur\w*|desfocad\w*|desenfoque|bokeh"),
    ("cámara", r"cameras?|camara|rec|recording|viewfinder"),
    ("fotos", r"photos?|fotos?|pictures?|collage|open image"),
    ("comida y bebida", r"drinks?|bebidas?|food|comida|legumes|verduras|pasta"),
    ("juegos", r"juegos?|jogos?|games?|gaming|arcade"),
    ("stickers", r"stickers?|pegatinas?"),
    ("naturaleza", r"nature|naturaleza|flowers?|flores|leaves|hojas|butterfly|rose"),
    ("amor", r"romantic|love|hearts?|corazon\w*|amor"),
    ("terror", r"horror|terror|creeps?|scary|dark side|halloween"),
    ("tutorial", r"tutorials?|tutoriales|como usar|how to"),
    # sonido
    ("whoosh", r"whoosh\w*|swoosh\w*|swish\w*|woosh\w*"),
    ("golpe", r"hits?|impacts?|impacto|slams?|punch|stinger|thud|stabing\w*"),
    ("subida", r"risers?|build ups?|subida|crescendos?|swell|rising\w*"),
    ("ambiente", r"ambien\w*|atmosph\w*|athmosph\w*|drones?"),
    ("percusión", r"drums?|drum hits|percussion|beats?|cymbals?"),
    ("ruido", r"noise\w*|ruidos?|static"),
    ("cuerdas", r"strings?|cuerdas|violin\w*|cello"),
    ("tensión", r"tension|suspense|dramatic\w*|dramatico"),
    ("épico", r"epic|trailer\w*"),
    ("divertido", r"funny|divertid\w*|engracad\w*"),
]

# Etiquetas de sonido que solo tienen sentido en archivos de audio.
AUDIO_ONLY = {"ruido", "cuerdas", "whoosh", "subida", "ambiente", "percusión", "tensión", "épico", "divertido"}
_MUSIC = re.compile(r"\b(musica|music|tracks?|songs?|soundtrack)\b")
_SFX = re.compile(r"\b(sfx|efectos de sonido|sound fx|sound effects?|sounds?|sonidos?|audio)\b")
_LOOP = re.compile(r"\b(loops?|bucles?|seamless|looped)\b")
_BPM = re.compile(r"\b(\d{2,3}) ?bpm\b")

_COMPILED = [(tag, re.compile(r"\b(?:" + pattern + r")\b")) for tag, pattern in VOCABULARY]

# Etiquetas que salen de la medición (no de la carpeta): la interfaz las agrupa aparte.
MEASURED = ["transparente", "4k", "full hd", "vertical", "horizontal", "cuadrado", "con sonido", "bucle"]


def compute_auto_tags(path: str, media_kind: str, ext: str, analysis: dict | None) -> list[str]:
    """Etiquetas deducidas de la ruta (pack + carpetas + nombre) y de lo medido."""
    text = normalize_text(path)
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    for tag, pattern in _COMPILED:
        if tag in AUDIO_ONLY and media_kind != "audio":
            continue
        if tag == "tutorial" and "thumbnails" in text:
            continue  # en algunos packs «Tutorials/Video_Thumbnails» son muestras del efecto, no tutoriales
        if pattern.search(text):
            add(tag)
    if media_kind == "audio":
        # «MÚSICA Y SONIDO/MUSICA/…/Swishes» es un efecto: mandan los sonidos reconocidos y, si no,
        # la carpeta más cercana al archivo que diga música o efecto.
        if any(t in tags for t in ("whoosh", "golpe", "subida", "glitch")):
            add("efecto de sonido")
        else:
            for segment in reversed(path.replace("\\", "/").split("/")[:-1]):
                seg = normalize_text(segment)
                if _SFX.search(seg):
                    add("efecto de sonido")
                    break
                if _MUSIC.search(seg):
                    add("música")
                    break
        bpm = _BPM.search(text)
        if bpm:
            add(f"{bpm.group(1)} bpm")
    if _LOOP.search(text):
        add("bucle")

    a = analysis or {}
    video = a.get("video") or {}
    image = a.get("image") or {}
    visual = video or image
    if visual.get("alpha_format") and visual.get("alpha_used", True) is not False:
        add("transparente")
    w, h = visual.get("width") or 0, visual.get("height") or 0
    long_side = max(w, h)
    if long_side >= 3800:
        add("4k")
    elif long_side >= 1900:
        add("full hd")
    orientation = a.get("orientation")
    if media_kind in ("video", "image") and orientation in ("vertical", "horizontal"):
        add(orientation)
    elif media_kind in ("video", "image") and orientation == "square":
        add("cuadrado")
    if media_kind == "video" and a.get("audio"):
        add("con sonido")
    fps = video.get("fps")
    if media_kind == "video" and fps and fps >= 47:
        add(f"{round(fps)} fps")
    if ext in (".cube", ".3dl", ".look"):
        add("lut")
    return tags


_ROWS = (
    "SELECT a.id, a.title, a.original_title, a.description, a.tags, a.auto_tags, a.search_text, v.media_kind, v.ext, v.analysis, "
    "(SELECT COALESCE(p.label || '/' || e.inner_path, l.rel_path) FROM locations l "
    " LEFT JOIN pack_entries e ON e.id = l.pack_entry_id LEFT JOIN packs p ON p.id = e.pack_id "
    " WHERE l.version_id = v.id ORDER BY (l.kind = 'pack') DESC, l.last_seen_at DESC LIMIT 1) AS path "
    "FROM assets a JOIN asset_versions v ON v.id = a.version_id"
)


def search_text_for(title: str, original_title: str, description: str, tags: list[str], auto_tags: list[str], path: str) -> str:
    return normalize_text(" ".join([title, original_title, description, " ".join(tags), " ".join(auto_tags), path or ""]))


def retag(db: Database, where: str = "", params: tuple = ()) -> int:
    """Recalcula etiquetas automáticas y texto de búsqueda de las fichas que cumplan `where`.
    Solo escribe las que cambian. Devuelve cuántas cambiaron."""
    rows = db.query(_ROWS + (f" WHERE {where}" if where else ""), params)
    changes = []
    for r in rows:
        auto = compute_auto_tags(r["path"] or r["original_title"], r["media_kind"], r["ext"], loads(r["analysis"], {}))
        search = search_text_for(r["title"], r["original_title"], r["description"], loads(r["tags"], []), auto, r["path"] or "")
        auto_json = json.dumps(auto, ensure_ascii=False)
        if auto_json != r["auto_tags"] or search != r["search_text"]:
            changes.append((auto_json, search, r["id"]))
    if changes:
        with db.tx() as conn:
            conn.executemany("UPDATE assets SET auto_tags = ?, search_text = ? WHERE id = ?", changes)
    return len(changes)


def ensure_auto_tags(db: Database) -> int:
    """Al arrancar: si el vocabulario cambió desde la última vez, recalcula todo el catálogo."""
    row = db.one("SELECT value FROM meta WHERE key = 'autotag_version'")
    if row and row["value"] == AUTOTAG_VERSION:
        return 0
    changed = retag(db)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('autotag_version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (AUTOTAG_VERSION,),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('autotag_at', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (now_iso(),),
        )
    return changed
