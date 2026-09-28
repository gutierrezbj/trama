"""Nivel 2: prueba de IA de visión con coste medido (modelos simulados: sin red ni gasto)."""
from __future__ import annotations

from conftest import import_all, wait_idle

from trama import vision


def test_model_reply_is_parsed_and_cleaned():
    desc, tags = vision._parse('Claro: {"description": "Humo blanco que sube", "tags": ["Smoke", "rising_smoke", "video", "smoke"]}')
    assert desc == "Humo blanco que sube" and tags == ["smoke", "rising smoke"]


def test_ai_test_compares_models_with_measured_cost_and_votes(env, monkeypatch):
    client = env["client"]
    import_all(client)
    wait_idle(client)
    st = client.app.state.trama
    st.settings.local_vision_url = "http://mac-simulado:1234/v1"
    st.settings.openai_api_key = "sk-prueba"
    seen_sheets = []

    def fake_describe(settings, model, sheet, hints, client=None):
        seen_sheets.append(sheet)
        if model == "local:roto":
            raise vision.VisionError("LM Studio apagado")
        return {"description": f"visto por {model}", "tags": ["test"], "input_tokens": 500, "output_tokens": 40,
                "cost_usd": 0.0001 if model.startswith("openai:") else 0.0, "seconds": 1.5}

    monkeypatch.setattr(vision, "describe", fake_describe)
    r = client.post("/api/ai/test", json={"models": ["openai:gpt-6-luna", "local:roto"], "size": 5})
    assert r.status_code == 202, r.text
    wait_idle(client)
    run = client.get("/api/ai/runs/latest").json()
    assert run["status"] == "done" and len(run["items"]) == 2  # vídeo opaco y vídeo con alfa
    assert all(p.exists() for p in seen_sheets)  # hoja de fotogramas generada desde la vista previa
    luna = next(s for s in run["summary"] if s["model"] == "openai:gpt-6-luna")
    roto = next(s for s in run["summary"] if s["model"] == "local:roto")
    assert luna["done"] == 2 and luna["errors"] == 0 and luna["projected_cost_usd"] == 0.0002
    assert roto["errors"] == 2  # el fallo de un modelo no para la prueba
    assert client.get(run["items"][0]["sheet_url"]).status_code == 200

    vid = run["items"][0]["version_id"]
    client.post(f"/api/ai/runs/{run['id']}/vote", json={"version_id": vid, "winner": "openai:gpt-6-luna"})
    again = client.get("/api/ai/runs/latest").json()
    assert next(s for s in again["summary"] if s["model"] == "openai:gpt-6-luna")["wins"] == 1


def test_reply_with_trailing_text_after_the_json_is_accepted():
    desc, tags = vision._parse('{"description": "Chispas", "tags": ["sparks"]}\n{"extra": 1}')
    assert desc == "Chispas" and tags == ["sparks"]
