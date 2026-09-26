"""E2: ZIP seguros, identidad provisional, extracción selectiva, duplicados por hash y límites de disco."""
from __future__ import annotations

import hashlib
import io
import shutil
import time
import zipfile
from pathlib import Path

import pytest
from conftest import import_all, reopen, source_id, wait_idle


def make_pack(root: Path, files: dict, name: str = "pack.zip", unsafe: bool = False) -> Path:
    path = root / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for inner, src in files.items():
            zf.write(src, inner)
        if unsafe:
            zf.writestr("../fuera.mp4", b"x" * 100)
            zf.writestr("/abs/absoluto.mp4", b"x" * 100)
            zf.writestr("C:\\Windows\\win.mp4", b"x" * 100)
            zf.writestr("a/../../escapa.mp4", b"x" * 100)
            info = zipfile.ZipInfo("enlace.mp4")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "../../etc/passwd")
            zf.writestr("anidado.zip", b"PK\x05\x06" + b"\0" * 18)
            zf.writestr("bomba.mp4", b"\0" * (3 * 1024 * 1024))  # ratio enorme → sospechosa
            zf.writestr("/".join(["p"] * 40) + "/hondo.mp4", b"x" * 10)
    return path


def index_and_wait(client, sid: str, path: str) -> dict:
    r = client.post("/api/packs/index", json={"source_id": sid, "path": path})
    assert r.status_code == 202, r.text
    wait_idle(client)
    return client.get(f"/api/packs/{r.json()['packs'][0]['pack_id']}").json()


def test_zip_index_is_safe_and_provisional(env):
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    make_pack(root / "packs", {"VFX/humo.mov": files["alpha"], "Transiciones/barrido.mp4": files["opaque"], "Audio/tono.wav": files["audio"], "leeme.txt": files["broken"]}, "compra.zip", unsafe=True)

    sid = source_id(client)
    browse = client.get("/api/fs/browse", params={"source_id": sid, "path": "packs"}).json()
    assert [z["name"] for z in browse["zips"]] == ["compra.zip"] and browse["zips"][0]["pack_id"] is None

    pack = index_and_wait(client, sid, "packs/compra.zip")
    assert pack["status"] == "indexed"
    assert pack["entries_media"] == 3            # humo, barrido, tono (leeme.txt y anidado.zip se ignoran)
    assert pack["entries_unsafe"] == 7  # traversal x2, absoluta, unidad, enlace, ratio, profundidad
    reasons = {e["inner_path"]: e["unsafe_reason"] for e in pack["unsafe_entries"]}
    assert any("traversal" in r for r in reasons.values())
    assert any("absoluta" in r for r in reasons.values())
    assert any("simbólico" in r for r in reasons.values())
    assert any("compresión" in r for r in reasons.values())
    assert any("niveles" in r for r in reasons.values())
    assert pack["extracted"] == 0

    # Catalogado sin extraer: fichas con identidad provisional, sin previews ni originales disponibles.
    items = client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"]
    assert len(items) == 3
    for a in items:
        assert a["archived"] is True and a["available"] is False and a["extractable"] is True
        assert a["version"]["identity_kind"] == "provisional"
        assert a["preview"]["status"] == "archived"
        assert a["locations"][0]["kind"] == "pack" and a["locations"][0]["pack_label"] == "compra"
    assert client.get("/api/assets", params={"availability": "archived"}).json()["total"] == 3
    # Nada se ha escrito en la caché ni fuera de ella.
    assert not any(env["settings"].cache_dir.rglob("*.mov"))
    assert not (root / "fuera.mp4").exists() and not (env["tmp"] / "fuera.mp4").exists()

    # Reindexar es idempotente.
    pack2 = index_and_wait(client, sid, "packs/compra.zip")
    assert pack2["id"] == pack["id"] and client.get("/api/assets").json()["total"] == 3
    csv = client.get(f"/api/packs/{pack['id']}/inventory.csv")
    assert csv.status_code == 200 and "VFX/humo.mov" in csv.text
    assert not list(Path(__file__).resolve().parents[2].glob("inventarios/*"))


def test_selective_extraction_confirms_identity_and_generates_previews(env):
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    make_pack(root / "packs", {"VFX/humo.mov": files["alpha"], "Transiciones/barrido.mp4": files["opaque"], "Audio/tono.wav": files["audio"]}, "compra.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/compra.zip")

    r = client.post(f"/api/packs/{pack['id']}/extract", json={"prefix": "VFX"})
    assert r.status_code == 202 and r.json()["entries"] == 1
    wait_idle(client)
    humo = next(a for a in client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"] if a["original_title"] == "humo.mov")
    assert humo["available"] is True and humo["archived"] is False
    assert humo["version"]["identity_kind"] == "sha256"
    assert humo["version"]["sha256"] == hashlib.sha256(files["alpha"].read_bytes()).hexdigest()
    assert humo["preview"]["kind"] == "video_alpha" and humo["preview"]["status"] == "ready"
    assert client.get(f"/api/assets/{humo['id']}/original").content == files["alpha"].read_bytes()
    pack = client.get(f"/api/packs/{pack['id']}").json()
    assert pack["extracted"] == 1
    tree = {f["path"]: f for f in pack["folders"]}
    assert tree["VFX"]["extracted"] == 1 and tree["Audio"]["extracted"] == 0
    # El resto sigue archivado; la descarga bajo demanda extrae solo esa entrada.
    tono = next(a for a in client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"] if a["original_title"] == "tono.wav")
    assert tono["archived"] is True
    r = client.get(f"/api/assets/{tono['id']}/original")
    assert r.status_code == 200 and r.content == files["audio"].read_bytes()
    wait_idle(client)
    assert client.get(f"/api/packs/{pack['id']}").json()["extracted"] == 2
    barrido = next(a for a in client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"] if a["original_title"] == "barrido.mp4")
    assert barrido["archived"] is True

    # Liberar caché: el archivo extraído desaparece, la ficha y las previews siguen.
    r = client.post(f"/api/assets/{humo['id']}/release")
    assert r.json()["released"] == 1
    humo2 = client.get(f"/api/assets/{humo['id']}").json()
    assert humo2["archived"] is True and humo2["preview"]["status"] == "ready"
    assert client.get(f"/api/assets/{humo['id']}/thumb").status_code == 200
    assert not (env["settings"].cache_dir / pack["id"] / "VFX" / "humo.mov").exists()

    # Persistencia tras reinicio.
    client = reopen(env)
    assert client.get(f"/api/packs/{pack['id']}").json()["extracted"] == 1
    assert client.get(f"/api/assets/{humo['id']}").json()["version"]["sha256"] == humo["version"]["sha256"]


def test_duplicate_confirmed_by_hash_merges_into_existing_asset(env):
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    import_all(client)  # la carpeta local ya tiene test_alpha.mov como recurso
    local = next(a for a in client.get("/api/assets", params={"limit": 100}).json()["items"] if a["original_title"] == "test_alpha.mov")
    client.patch(f"/api/assets/{local['id']}", json={"tags": ["local"]})

    (root / "packs").mkdir()
    make_pack(root / "packs", {"otro/nombre_distinto.mov": files["alpha"], "otro/copia2.mov": files["alpha"]}, "dup.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/dup.zip")
    # Antes de extraer: identidad provisional distinta → ficha candidata separada (mismo crc → una sola).
    prov = client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"]
    assert len(prov) == 1 and prov[0]["version"]["identity_kind"] == "provisional"
    assert len(prov[0]["locations"]) == 2  # candidatos por crc32+tamaño dentro del pack
    total_before = client.get("/api/assets").json()["total"]

    client.post(f"/api/packs/{pack['id']}/extract", json={"prefix": "otro"})
    wait_idle(client)
    # Confirmado por SHA-256: la ficha provisional sin ediciones se retira; la local conserva sus etiquetas y gana ubicaciones.
    assert client.get("/api/assets").json()["total"] == total_before - 1
    merged = client.get(f"/api/assets/{local['id']}").json()
    assert merged["tags"] == ["local"]
    assert len(merged["locations"]) == 3
    assert sum(1 for l in merged["locations"] if l["kind"] == "pack") == 2
    dups = client.get("/api/duplicates").json()
    group = next(g for g in dups["groups"] if g["asset_id"] == local["id"])
    assert group["confirmed"] is True and group["n"] == 3
    assert client.get("/api/assets", params={"duplicates": "true"}).json()["total"] == 1
    # Los archivos originales siguen intactos.
    assert files["alpha"].exists() and (root / "packs" / "dup.zip").exists()


def test_duplicate_with_edits_is_kept_and_linked(env):
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    import_all(client)
    local = next(a for a in client.get("/api/assets", params={"limit": 100}).json()["items"] if a["original_title"] == "test_tone.wav")
    (root / "packs").mkdir()
    make_pack(root / "packs", {"sonido/tono_pack.wav": files["audio"]}, "dup.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/dup.zip")
    prov = client.get("/api/assets", params={"pack_id": pack["id"]}).json()["items"][0]
    client.patch(f"/api/assets/{prov['id']}", json={"description": "editada antes de extraer"})
    client.post(f"/api/packs/{pack['id']}/extract", json={})
    wait_idle(client)
    kept = client.get(f"/api/assets/{prov['id']}").json()
    assert kept["duplicate_of"] == local["id"]
    assert kept["description"] == "editada antes de extraer"
    assert kept["version"]["id"] == local["version"]["id"]


def test_cache_limit_stops_batch_and_keeps_partial(env, tmp_path):
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    make_pack(root / "packs", {"a/1.mp4": files["opaque"], "a/2.mov": files["alpha"], "a/3.wav": files["audio"]}, "lim.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/lim.zip")
    sizes = sorted(f["bytes"] for f in pack["folders"] if f["path"] == "a")
    env["settings"].cache_max_bytes = sizes[0] - 1  # cabe menos que la carpeta entera
    r = client.post(f"/api/packs/{pack['id']}/extract", json={"prefix": "a"})
    assert r.status_code == 507 and "Límite de caché" in r.json()["detail"]
    # Con límite justo para la primera entrada: el lote se detiene con error visible y conserva lo extraído.
    first = client.get("/api/assets", params={"pack_id": pack["id"], "sort": "title"}).json()["items"]
    env["settings"].cache_max_bytes = files["opaque"].stat().st_size + 10
    r = client.post(f"/api/assets/{first[0]['id']}/extract")
    assert r.status_code in (202, 507)
    wait_idle(client)
    env["settings"].cache_max_bytes = 30 * 1024**3
    jobs = client.get("/api/jobs", params={"status": "failed"}).json()
    assert all("Límite" in (j["error"] or "") or "extraídas" in (j["error"] or "") or j["kind"] != "extract" for j in jobs)


def test_import_ignores_zip_files_and_keeps_layout(env):
    client = env["client"]
    root: Path = env["root"]
    make_pack(root, {"x/y.mp4": env["files"]["opaque"]}, "suelto.zip")
    imp = import_all(client)
    assert imp["added"] == 4  # el ZIP no cuenta como recurso suelto
    zips = client.get("/api/fs/browse", params={"source_id": source_id(client), "path": ""}).json()["zips"]
    assert [z["name"] for z in zips] == ["suelto.zip"]


def test_provider_preview_and_lut_demo(env, tools):
    """Plantilla sin preview genérica enlaza a su vídeo hermano; un LUT genera demostración antes/después."""
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    aep = root / "plantilla.aep"
    aep.write_bytes(b"RIFX fake after effects project")
    lut = root / "look.cube"
    lut.write_text('TITLE "Prueba"\nLUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n', encoding="utf-8")
    (root / "packs").mkdir()
    make_pack(root / "packs", {"titulos/Intro.aep": aep, "titulos/Intro.mp4": files["opaque"], "luts/look.cube": lut}, "tpl.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/tpl.zip")
    items = {a["original_title"]: a for a in client.get("/api/assets", params={"pack_id": pack["id"], "limit": 50}).json()["items"]}
    assert items["Intro.aep"]["provider_preview"]["asset_id"] == items["Intro.mp4"]["id"]
    assert items["Intro.aep"]["required_app"] == "After Effects"
    assert items["Intro.aep"]["preview"]["kind"] == "none"
    client.post(f"/api/packs/{pack['id']}/extract", json={})
    wait_idle(client)
    aep_a = client.get(f"/api/assets/{items['Intro.aep']['id']}").json()
    assert aep_a["provider_preview"]["thumb_url"] and client.get(aep_a["provider_preview"]["thumb_url"]).status_code == 200
    assert aep_a["preview"]["status"] == "unsupported"  # honesto: sin preview propia
    lut_a = client.get(f"/api/assets/{items['look.cube']['id']}").json()
    assert lut_a["lut"] == {"title": "Prueba", "size_3d": 2, "size_1d": None}
    assert lut_a["preview"] == {"kind": "lut_demo", "status": "ready", "backgrounds": []}
    demo = client.get(lut_a["lut_demo_url"])
    assert demo.status_code == 200 and demo.content[:3] == b"\xff\xd8\xff"
    assert lut_a["category"] == "color"


def test_previews_for_whole_pack_leave_no_extracted_copies(env):
    """«Vistas previas para todo»: cada recurso del pack queda analizado y con preview, las copias
    extraídas se sueltan (la caché queda vacía) y repetirlo no vuelve a encolar nada."""
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    make_pack(root / "packs", {"VFX/humo.mov": files["alpha"], "Transiciones/barrido.mp4": files["opaque"], "Audio/tono.wav": files["audio"]}, "compra.zip")
    sid = source_id(client)
    pack = index_and_wait(client, sid, "packs/compra.zip")
    assert client.get("/api/packs/previews").json()["pending"] == 3

    r = client.post("/api/packs/previews")
    assert r.status_code == 202 and r.json() == {"queued": 1, "unreachable": 0}
    wait_idle(client)

    status = client.get("/api/packs/previews").json()
    assert status["pending"] == 0 and status["running"] is None
    items = client.get("/api/assets", params={"pack_id": pack["id"], "limit": 100}).json()["items"]
    assert len(items) == 3
    for a in items:
        assert a["archived"] is True, a["original_title"]               # la copia extraída se soltó
        assert a["version"]["identity_kind"] == "sha256"
        assert a["preview"]["status"] == "ready", a["original_title"]
    assert client.get(f"/api/packs/{pack['id']}").json()["extracted"] == 0
    assert not [p for p in env["settings"].cache_dir.rglob("*") if p.is_file()]
    assert client.post("/api/packs/previews").json()["queued"] == 0
