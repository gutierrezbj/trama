"""Etiquetas de nivel 1: deducidas de las carpetas del pack y de los datos medidos.

Sin IA y sin coste. Los packs mezclan inglés, español y portugués («Smoke», «Humo», «Fumaça»):
cada etiqueta canónica, en inglés del oficio, reúne sus sinónimos y guarda un alias en español
para la búsqueda. Van en `assets.auto_tags`, aparte de las
etiquetas humanas, y se recalculan enteras cuando cambia el vocabulario (AUTOTAG_VERSION).
"""
from __future__ import annotations

import json
import re

from .db import Database, loads, normalize_text, now_iso
from .importer import clean_title, smart_title

# Súbase al cambiar el vocabulario o las reglas: el arranque recalcula todo el catálogo.
AUTOTAG_VERSION = "4"

# (etiqueta, alias en español, sinónimos). La etiqueta va en el inglés estándar del oficio (el de
# DaVinci, Premiere y los packs); el alias en español solo entra en la búsqueda: «humo» encuentra
# «smoke». Los sinónimos son expresiones sobre texto normalizado (minúsculas, sin acentos,
# separadores como espacios) y se buscan como palabras completas; `\w*` alarga un prefijo.
VOCABULARY: list[tuple[str, str, str]] = [
    # efectos visuales
    ("smoke", "humo", r"smoke\w*|humo|fumaca|fumo|vapor|steam"),
    ("fire", "fuego", r"fire|fires|fuego|fogo|flames?|llamas?"),
    ("explosion", "", r"explo\w*|bursts?|bombs?|blast\w*|charges?|detona\w*"),
    ("sparks", "chispas", r"sparks?|chispas?|faiscas?|eletrify|electrify"),
    ("particles", "partículas", r"particles?|particulas?|particle\w*"),
    ("dust", "polvo", r"dust\w*|polvo|powder|poeira|debris|dirt\w*"),
    ("blood", "sangre", r"blood|sangre|sangue"),
    ("water", "agua", r"water|agua|splash\w*|drops?|gotas?|liquid\w*"),
    ("rain", "lluvia", r"rain|lluvia|chuva|thunderstorm|storm"),
    ("broken glass", "cristal roto", r"glass|cristal|vidrio|windshields?|cracks?|shatter\w*"),
    ("muzzle flash", "disparos", r"muzzle\w*|bullet\w*|shells?|gun\w*|disparos?"),
    ("electricity", "electricidad", r"electric\w*|eletric\w*|lightning|thunder|rayos?|energy"),
    ("magic", "magia", r"magic|magico|magia|fairy|shimmer|sakura"),
    ("glow", "brillo", r"glow|shine|brillo|bright\w*|prism\w*|diamonds?"),
    ("flare", "destello", r"flares?|lens flare|destellos?|flash|flashes"),
    ("light leaks", "fugas de luz", r"light leaks?|leaks?|luzes|luces|light transitions?"),
    ("burn", "quemado", r"film burns?|burn marks?|burn|burns|burning|quemad\w*|film damage"),
    ("film", "película", r"film|films|filme|16mm|8mm|super 8|film leaders?|perforation|celuloide"),
    ("grain", "grano", r"grain|grano|granulado"),
    ("vhs", "", r"vhs|camcorder\w*|digital8"),
    ("crt", "tv antigua", r"crt|old tv|tv noise|static|analog\w*|interferenc\w*"),
    ("glitch", "", r"glitch\w*"),
    ("neon", "", r"neon|led"),
    ("hud", "", r"hud|huds|hologram\w*|holografic\w*|holographic|interface|visual systems|terminal"),
    ("futuristic", "futurista", r"futur\w*|sci fi|scifi|cyber\w*|tech|digital"),
    ("hand drawn", "dibujado a mano", r"sketch\w*|scribble\w*|doodle\w*|hand drawn|written|garabatos?|dibujad\w*"),
    ("paper", "papel", r"paper|papel|postit|paper rip\w*|origami"),
    ("tape", "cinta adhesiva", r"scotch|duck tape|tape|cinta"),
    ("texture", "textura", r"textur\w*|marble|metal|wood|plastic|photocopy|gradient|grunge"),
    ("grunge", "", r"grunge"),
    ("background", "fondo", r"backgrounds?|fondos?|backdrops?|bg"),
    ("shapes", "formas", r"lines|shapes?|formas?|figuras?|abstract\w*|circles?|squares?|geometr\w*"),
    ("arrows", "flechas", r"arrows?|flechas?|setas?"),
    ("emoji", "", r"emojis?|emoticon\w*"),
    ("hands", "manos", r"hands?|manos|maos|gestos"),
    ("social media", "redes sociales", r"social|redes|sociais|twitter|instagram|youtube|tiktok|facebook|like|dislike|subscribe|suscri\w*"),
    ("notifications", "notificaciones", r"notifica\w*|notification\w*|alerts?|warning|error"),
    ("numbers", "números", r"numbers?|numeros?|numerals?|counter|contador|countdown"),
    ("typography", "tipografía", r"letters?|letras?|fonts?|tipografia|typograph\w*|alphabet|upper case|lower case|characters|letter"),
    ("titles", "títulos", r"titles?|titulos?|intro|abertura"),
    ("lower thirds", "rótulos", r"lower thirds?|tercios inferiores|rotulos?|callouts?"),
    ("frames", "marcos", r"frames?|marcos?|letterbox|aspect ratio|borders?|bordes?"),
    ("cartoon", "", r"cartoon\w*|comics?|comic|ballons|balloons|bocadillos?"),
    ("birthday", "cumpleaños", r"cumpleanos|cumpeanos|birthday|aniversario"),
    ("money", "dinero", r"money|dinero|dinheiro|cash|chash|cassino|casino"),
    ("retro", "", r"retro|vintage|old|antigu\w*"),
    ("wipe", "barrido", r"wipes?|swipes?|slides?|deslizantes"),
    ("objects", "objetos", r"objects?|objetos?|objectos?"),
    ("brush", "pinceladas", r"brush\w*|pincel\w*|brochazos?|paint strokes?"),
    ("blur", "desenfoque", r"blur\w*|desfocad\w*|desenfoque|bokeh"),
    ("camera", "cámara", r"cameras?|camara|rec|recording|viewfinder"),
    ("photos", "fotos", r"photos?|fotos?|pictures?|collage|open image"),
    ("food & drink", "comida y bebida", r"drinks?|bebidas?|food|comida|legumes|verduras|pasta"),
    ("games", "juegos", r"juegos?|jogos?|games?|gaming|arcade"),
    ("stickers", "", r"stickers?|pegatinas?"),
    ("nature", "naturaleza", r"nature|naturaleza|flowers?|flores|leaves|hojas|butterfly|rose"),
    ("love", "amor", r"romantic|love|hearts?|corazon\w*|amor"),
    ("horror", "terror", r"horror|terror|creeps?|scary|dark side|halloween"),
    ("tutorial", "", r"tutorials?|tutoriales|como usar|how to"),
    # sonido
    ("whoosh", "", r"whoosh\w*|swoosh\w*|swish\w*|woosh\w*"),
    ("impact", "golpe", r"hits?|impacts?|impacto|slams?|punch|stinger|thud|stabing\w*"),
    ("riser", "subida", r"risers?|build ups?|subida|crescendos?|swell|rising\w*"),
    ("ambience", "ambiente", r"ambien\w*|atmosph\w*|athmosph\w*|drones?"),
    ("drums", "percusión", r"drums?|drum hits|percussion|beats?|cymbals?"),
    ("noise", "ruido", r"noise\w*|ruidos?|static"),
    ("strings", "cuerdas", r"strings?|cuerdas|violin\w*|cello"),
    ("tension", "", r"tension|suspense|dramatic\w*|dramatico"),
    ("epic", "épico", r"epic|trailer\w*"),
    ("funny", "divertido", r"funny|divertid\w*|engracad\w*"),
]

# Etiquetas de sonido que solo tienen sentido en archivos de audio.
AUDIO_ONLY = {"noise", "strings", "whoosh", "riser", "ambience", "drums", "tension", "epic", "funny"}
_MUSIC = re.compile(r"\b(musica|music|tracks?|songs?|soundtrack)\b")
_SFX = re.compile(r"\b(sfx|efectos de sonido|sound fx|sound effects?|sounds?|sonidos?|audio)\b")
_LOOP = re.compile(r"\b(loops?|bucles?|seamless|looped)\b")
_BPM = re.compile(r"\b(\d{2,3}) ?bpm\b")

_COMPILED = [(tag, re.compile(r"\b(?:" + pattern + r")\b")) for tag, _alias, pattern in VOCABULARY]

# Alias en español para buscar, también los de las medidas y del tipo de audio.
ALIASES: dict[str, str] = {tag: alias for tag, alias, _pattern in VOCABULARY if alias}
ALIASES.update({"alpha": "transparente transparencia alfa", "with audio": "con sonido", "loop": "bucle", "music": "musica",
                "sfx": "efecto de sonido efectos", "square": "cuadrado", "full hd": "1080"})

# Color y luz medidos en la miniatura (ver media.measure_look).
COLOR_TAGS = ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta", "black & white", "dark", "bright", "black background"]
ALIASES.update({"red": "rojo", "orange": "naranja", "yellow": "amarillo", "green": "verde", "cyan": "cian turquesa",
                "blue": "azul", "purple": "morado violeta", "magenta": "magenta rosa fucsia", "black & white": "blanco y negro",
                "dark": "oscuro", "bright": "claro luminoso", "black background": "fondo negro"})


def look_tags(look: dict | None, has_alpha: bool) -> list[str]:
    """Etiquetas de color y luz. Con alfa la miniatura va sobre damero: no se juzga el fondo."""
    if not look:
        return []
    tags: list[str] = []
    if look.get("colorful", 0) >= 0.02:
        for name, share in list(look.get("hues", {}).items())[:2]:
            if share >= 0.25:
                tags.append(name)
    elif look.get("colorful", 0) < 0.005 and not has_alpha:
        tags.append("black & white")
    if not has_alpha:
        if look.get("black", 0) >= 0.55:
            tags.append("black background")
        elif look.get("luma", 0.5) < 0.2:
            tags.append("dark")
        if look.get("luma", 0) > 0.7:
            tags.append("bright")
    return tags


# Etiquetas que salen de la medición (no de la carpeta): la interfaz las agrupa aparte.
MEASURED = ["alpha", "4k", "full hd", "vertical", "horizontal", "square", "with audio", "loop", "lut"]


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
        if any(t in tags for t in ("whoosh", "impact", "riser", "glitch")):
            add("sfx")
        else:
            for segment in reversed(path.replace("\\", "/").split("/")[:-1]):
                seg = normalize_text(segment)
                if _SFX.search(seg):
                    add("sfx")
                    break
                if _MUSIC.search(seg):
                    add("music")
                    break
        bpm = _BPM.search(text)
        if bpm:
            add(f"{bpm.group(1)} bpm")
    if _LOOP.search(text):
        add("loop")

    a = analysis or {}
    video = a.get("video") or {}
    image = a.get("image") or {}
    visual = video or image
    if visual.get("alpha_format") and visual.get("alpha_used", True) is not False:
        add("alpha")
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
        add("square")
    if media_kind == "video" and a.get("audio"):
        add("with audio")
    fps = video.get("fps")
    if media_kind == "video" and fps and fps >= 47:
        add(f"{round(fps)} fps")
    if ext in (".cube", ".3dl", ".look"):
        add("lut")
    if media_kind in ("video", "image"):
        for t in look_tags(a.get("look"), bool(visual.get("alpha_format"))):
            add(t)
    return tags


_ROWS = (
    "SELECT a.id, a.title, a.title_source, a.original_title, a.description, a.tags, a.auto_tags, a.search_text, v.media_kind, v.ext, v.analysis, "
    "(SELECT COALESCE(p.label || '/' || e.inner_path, l.rel_path) FROM locations l "
    " LEFT JOIN pack_entries e ON e.id = l.pack_entry_id LEFT JOIN packs p ON p.id = e.pack_id "
    " WHERE l.version_id = v.id ORDER BY (l.kind = 'pack') DESC, l.last_seen_at DESC LIMIT 1) AS path "
    "FROM assets a JOIN asset_versions v ON v.id = a.version_id"
)


def search_text_for(title: str, original_title: str, description: str, tags: list[str], auto_tags: list[str], path: str) -> str:
    aliases = [ALIASES.get(t, "") for t in auto_tags]
    return normalize_text(" ".join([title, original_title, description, " ".join(tags), " ".join(auto_tags), " ".join(aliases), path or ""]))


def retag(db: Database, where: str = "", params: tuple = ()) -> int:
    """Recalcula etiquetas automáticas, título deducido y texto de búsqueda de las fichas que
    cumplan `where`. Los títulos puestos a mano no se tocan. Solo escribe las que cambian.
    Devuelve cuántas cambiaron."""
    rows = db.query(_ROWS + (f" WHERE {where}" if where else ""), params)
    changes = []
    for r in rows:
        path = r["path"] or r["original_title"]
        auto = compute_auto_tags(path, r["media_kind"], r["ext"], loads(r["analysis"], {}))
        title, source = r["title"], r["title_source"]
        if source == "file" and title != clean_title(r["original_title"]):
            source = "human"  # editado a mano antes de que existiera title_source
        if source != "human":
            smart = smart_title(r["original_title"], path)
            title, source = (smart, "folder") if smart else (clean_title(r["original_title"]), "file")
        search = search_text_for(title, r["original_title"], r["description"], loads(r["tags"], []), auto, r["path"] or "")
        auto_json = json.dumps(auto, ensure_ascii=False)
        if auto_json != r["auto_tags"] or search != r["search_text"] or title != r["title"] or source != r["title_source"]:
            changes.append((auto_json, search, title, source, r["id"]))
    if changes:
        with db.tx() as conn:
            conn.executemany("UPDATE assets SET auto_tags = ?, search_text = ?, title = ?, title_source = ? WHERE id = ?", changes)
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
