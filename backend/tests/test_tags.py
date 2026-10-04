"""Etiquetado de nivel 1: carpetas en tres idiomas y datos medidos, sin pisar lo humano."""
from __future__ import annotations

from conftest import import_all, wait_idle

from trama.tags import compute_auto_tags, ensure_auto_tags


def test_folder_synonyms_in_three_languages_become_one_english_tag():
    assert "smoke" in compute_auto_tags("Pack/SMOKE/Smoke 04.mov", "video", ".mov", {})
    assert "smoke" in compute_auto_tags("Pack/FUMAÇA/fumaca 1.mp4", "video", ".mp4", {})
    assert "smoke" in compute_auto_tags("Pack/Humo denso/a.mp4", "video", ".mp4", {})
    # búsqueda en español por el alias
    from trama.tags import search_text_for
    assert "humo" in search_text_for("Smoke 04", "Smoke 04.mov", "", [], ["smoke"], "Pack/SMOKE/Smoke 04.mov")
    # palabra completa: «smokey» no es un error, pero «firewall» no es fuego
    assert "fire" not in compute_auto_tags("Pack/firewall/a.mp4", "video", ".mp4", {})


def test_sound_effect_beats_music_root_folder():
    tags = compute_auto_tags("Pack/MÚSICA Y SONIDO/MUSICA/Libreria/Swishes (100)/Swish 03.wav", "audio", ".wav", {})
    assert "whoosh" in tags and "sfx" in tags and "music" not in tags
    tags = compute_auto_tags("Pack/MÚSICA Y SONIDO/MUSICA/Ritmos/120BPM/loop 1.wav", "audio", ".wav", {})
    assert tags == ["music", "120 bpm", "loop"]
    # las etiquetas de sonido no se cuelan en vídeos
    assert "whoosh" not in compute_auto_tags("Pack/Whoosh transitions/a.mp4", "video", ".mp4", {})


def test_measured_tags():
    analysis = {"video": {"width": 2160, "height": 3840, "fps": 59.94, "alpha_format": 1, "alpha_used": True}, "orientation": "vertical", "audio": {"codec": "aac"}}
    tags = compute_auto_tags("Pack/x.mov", "video", ".mov", analysis)
    assert tags == ["alpha", "4k", "vertical", "with audio", "60 fps"]
    # alfa declarado pero no usado (todo opaco) no cuenta como transparente
    analysis["video"]["alpha_used"] = False
    assert "alpha" not in compute_auto_tags("Pack/x.mov", "video", ".mov", analysis)


def test_auto_tags_are_searchable_filterable_and_separate_from_human_tags(env):
    client = env["client"]
    import_all(client)
    wait_idle(client)
    items = client.get("/api/assets", params={"limit": 50}).json()["items"]
    alpha = next(a for a in items if a["original_title"] == "test_alpha.mov")
    assert {"alpha", "vertical"} <= set(alpha["auto_tags"])
    assert alpha["tags"] == []

    # filtro por etiqueta (automática) y búsqueda en español por su alias
    r = client.get("/api/assets", params={"tag": "alpha"}).json()
    assert [a["id"] for a in r["items"]] == [alpha["id"]]
    assert client.get("/api/assets", params={"q": "transparente"}).json()["total"] >= 1

    # una etiqueta humana convive, se filtra igual y aparece como manual
    client.patch(f"/api/assets/{alpha['id']}", json={"tags": ["intro spot"]})
    assert client.get("/api/assets", params={"tag": "alpha,intro spot"}).json()["total"] == 1
    assert client.get("/api/assets", params={"q": "intro spot"}).json()["total"] == 1
    kinds = {t["tag"]: t["kind"] for t in client.get("/api/tags").json()}
    assert kinds["intro spot"] == "manual" and kinds["alpha"] == "medida"

    # recalcular no toca las etiquetas humanas; con la misma versión no hace nada
    db = client.app.state.trama.db
    db.conn.execute("DELETE FROM meta WHERE key = 'autotag_version'")
    ensure_auto_tags(db)
    assert ensure_auto_tags(db) == 0
    again = client.get(f"/api/assets/{alpha['id']}").json()
    assert again["tags"] == ["intro spot"] and "alpha" in again["auto_tags"]


def test_meaningless_file_names_get_a_title_from_their_folders():
    from trama.importer import smart_title

    assert smart_title("_12.mp4", "Pack/MEGA PACK EDICIÓN/TRANSICIONES/COLOR TRANSITIONS/_12.mp4") == "Color Transitions · 12"
    assert smart_title("F.mov", "BUNDLE/CRT FONTS/CLASSIC/UPPER CASE/F.mov") == "CRT Fonts · Classic · F"
    assert smart_title("195.cube", "Pack/Luts Collections/195.cube") == "LUT 195"
    assert smart_title("Smoke 04.mov", "Pack/Smoke/Smoke 04.mov") is None


def test_folder_titles_are_applied_but_human_titles_are_kept(env):
    client = env["client"]
    import_all(client)
    wait_idle(client)
    db = client.app.state.trama.db
    items = client.get("/api/assets", params={"limit": 50}).json()["items"]
    a = next(x for x in items if x["original_title"] == "test_opaque.mp4")  # en «Transiciones/»
    b = next(x for x in items if x["original_title"] == "test_alpha.mov")
    # simula dos archivos con nombre sin palabras dentro de una carpeta con nombre
    db.conn.execute("UPDATE assets SET original_title = '2.mp4', title = '2' WHERE id IN (?, ?)", (a["id"], b["id"]))
    client.patch(f"/api/assets/{b['id']}", json={"title": "Mi favorito"})
    from trama.tags import retag
    retag(db)
    got_a = client.get(f"/api/assets/{a['id']}").json()
    got_b = client.get(f"/api/assets/{b['id']}").json()
    assert got_a["title"] == "Transiciones · 2" and got_a["title_source"] == "folder"
    assert got_b["title"] == "Mi favorito" and got_b["title_source"] == "human"


def test_look_tags_from_measured_color_and_light():
    from trama.tags import look_tags

    purple = {"hues": {"magenta": 0.8, "blue": 0.2}, "colorful": 0.6, "luma": 0.4, "black": 0.1}
    assert look_tags(purple, has_alpha=False) == ["magenta"]
    sparks = {"hues": {"orange": 0.7, "yellow": 0.3}, "colorful": 0.05, "luma": 0.08, "black": 0.8}
    assert look_tags(sparks, has_alpha=False) == ["orange", "yellow", "black background"]
    # con alfa la miniatura va sobre damero: ni fondo negro ni blanco y negro
    assert look_tags({"hues": {}, "colorful": 0.0, "luma": 0.1, "black": 0.9}, has_alpha=True) == []


def test_color_is_measured_from_thumbnails_and_tag_counts_follow_the_view(env):
    client = env["client"]
    import_all(client)
    wait_idle(client)
    items = client.get("/api/assets", params={"limit": 50}).json()["items"]
    opaque = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    look = client.get(f"/api/assets/{opaque['id']}").json()["analysis"]["look"]
    assert look["colorful"] > 0.5 and len(look["hues"]) >= 5  # carta de ajuste: muchos colores
    # los recuentos de etiquetas siguen a la vista: en audio no hay «alpha» ni «vertical»
    audio = {t["tag"] for t in client.get("/api/tags", params={"media_kind": "audio"}).json()}
    assert "alpha" not in audio and "vertical" not in audio
    assert "alpha" in {t["tag"] for t in client.get("/api/tags").json()}


def test_measure_look_names_the_dominant_color(tmp_path):
    from PIL import Image

    from trama.media import measure_look
    from trama.tags import look_tags

    path = tmp_path / "violeta.jpg"
    Image.new("RGB", (200, 120), (200, 20, 200)).save(path)
    look = measure_look(path)
    assert list(look["hues"]) == ["magenta"] and look_tags(look, has_alpha=False) == ["magenta"]


def test_animated_gif_thumbnail_uses_the_middle_frame(tmp_path):
    """El primer fotograma de un GIF animado suele estar en blanco: la miniatura sale del central."""
    from PIL import Image

    from trama.config import Settings
    from trama.media import generate_derivative

    frames = [Image.new("RGB", (40, 40), c) for c in ((255, 255, 255), (255, 255, 255), (220, 30, 30), (220, 30, 30))]
    gif = tmp_path / "anim.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    settings = Settings(data_dir=tmp_path, allowed_roots=[])
    settings.ensure_dirs()
    dest = tmp_path / "thumb.jpg"
    generate_derivative(settings, None, "thumb", gif, {"media_kind": "image"}, dest, None)
    r, g, b = Image.open(dest).convert("RGB").getpixel((20, 20))
    assert r > 180 and g < 90  # rojo del fotograma central, no blanco


def test_degenerate_twin_clusters_are_dropped(tmp_path):
    """Si una huella «se parece» a decenas de recursos a la vez, no son versiones: se descartan."""
    from trama.db import Database
    from trama import twins

    db = Database(tmp_path / "c.sqlite")
    db.migrate()
    tiny = bytes([10] * 512 + [200] * 512)
    with db.tx() as conn:
        for i in range(30):
            vid = f"ver_{i}"
            conn.execute("INSERT INTO asset_versions(id, sha256, size, ext, media_kind, analysis_status, created_at) VALUES (?, ?, 1, '.gif', 'image', 'done', 'x')", (vid, vid))
            conn.execute("INSERT INTO assets(id, version_id, original_title, title, created_at, updated_at) VALUES (?, ?, 'a', 'a', 'x', 'x')", (f"ast_{i}", vid))
            conn.execute("INSERT INTO vprints(version_id, dhash, tiny, flat, aspect, duration, media_kind, created_at) VALUES (?, ?, ?, 0, 1.0, NULL, 'image', 'x')",
                         (vid, "f" * 64, tiny))
    assert twins.rebuild_twins(db) == 0
