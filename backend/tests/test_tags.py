"""Etiquetado de nivel 1: carpetas en tres idiomas y datos medidos, sin pisar lo humano."""
from __future__ import annotations

from conftest import import_all, wait_idle

from trama.tags import compute_auto_tags, ensure_auto_tags


def test_folder_synonyms_in_three_languages_become_one_spanish_tag():
    assert "humo" in compute_auto_tags("Pack/SMOKE/Smoke 04.mov", "video", ".mov", {})
    assert "humo" in compute_auto_tags("Pack/FUMAÇA/fumaca 1.mp4", "video", ".mp4", {})
    assert "humo" in compute_auto_tags("Pack/Humo denso/a.mp4", "video", ".mp4", {})
    # palabra completa: «smokey» no es un error, pero «firewall» no es fuego
    assert "fuego" not in compute_auto_tags("Pack/firewall/a.mp4", "video", ".mp4", {})


def test_sound_effect_beats_music_root_folder():
    tags = compute_auto_tags("Pack/MÚSICA Y SONIDO/MUSICA/Libreria/Swishes (100)/Swish 03.wav", "audio", ".wav", {})
    assert "whoosh" in tags and "efecto de sonido" in tags and "música" not in tags
    tags = compute_auto_tags("Pack/MÚSICA Y SONIDO/MUSICA/Ritmos/120BPM/loop 1.wav", "audio", ".wav", {})
    assert tags == ["música", "120 bpm", "bucle"]
    # las etiquetas de sonido no se cuelan en vídeos
    assert "whoosh" not in compute_auto_tags("Pack/Whoosh transitions/a.mp4", "video", ".mp4", {})


def test_measured_tags():
    analysis = {"video": {"width": 2160, "height": 3840, "fps": 59.94, "alpha_format": 1, "alpha_used": True}, "orientation": "vertical", "audio": {"codec": "aac"}}
    tags = compute_auto_tags("Pack/x.mov", "video", ".mov", analysis)
    assert tags == ["transparente", "4k", "vertical", "con sonido", "60 fps"]
    # alfa declarado pero no usado (todo opaco) no cuenta como transparente
    analysis["video"]["alpha_used"] = False
    assert "transparente" not in compute_auto_tags("Pack/x.mov", "video", ".mov", analysis)


def test_auto_tags_are_searchable_filterable_and_separate_from_human_tags(env):
    client = env["client"]
    import_all(client)
    wait_idle(client)
    items = client.get("/api/assets", params={"limit": 50}).json()["items"]
    alpha = next(a for a in items if a["original_title"] == "test_alpha.mov")
    assert {"transparente", "vertical"} <= set(alpha["auto_tags"])
    assert alpha["tags"] == []

    # filtro por etiqueta (automática) y búsqueda en español
    r = client.get("/api/assets", params={"tag": "transparente"}).json()
    assert [a["id"] for a in r["items"]] == [alpha["id"]]
    assert client.get("/api/assets", params={"q": "transparente"}).json()["total"] >= 1

    # una etiqueta humana convive, se filtra igual y aparece como manual
    client.patch(f"/api/assets/{alpha['id']}", json={"tags": ["intro spot"]})
    assert client.get("/api/assets", params={"tag": "transparente,intro spot"}).json()["total"] == 1
    assert client.get("/api/assets", params={"q": "intro spot"}).json()["total"] == 1
    kinds = {t["tag"]: t["kind"] for t in client.get("/api/tags").json()}
    assert kinds["intro spot"] == "manual" and kinds["transparente"] == "medida"

    # recalcular no toca las etiquetas humanas; con la misma versión no hace nada
    db = client.app.state.trama.db
    db.conn.execute("DELETE FROM meta WHERE key = 'autotag_version'")
    ensure_auto_tags(db)
    assert ensure_auto_tags(db) == 0
    again = client.get(f"/api/assets/{alpha['id']}").json()
    assert again["tags"] == ["intro spot"] and "transparente" in again["auto_tags"]
