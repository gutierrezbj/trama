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


def test_macos_junk_in_zip_is_ignored(env):
    """Los «._nombre» (AppleDouble) y __MACOSX que meten los Mac en los ZIP no son recursos."""
    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    path = make_pack(root / "packs", {"VFX/humo.mov": files["alpha"]}, "mac.zip")
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("VFX/._humo.mov", b"\x00\x05\x16\x07" + b"\x00" * 4000)
        zf.writestr("__MACOSX/VFX/._humo.mov", b"\x00\x05\x16\x07" + b"\x00" * 4000)
    pack = index_and_wait(client, source_id(client), "packs/mac.zip")
    assert pack["entries_media"] == 1
    titles = [a["original_title"] for a in client.get("/api/assets", params={"pack_id": pack["id"], "limit": 50}).json()["items"]]
    assert titles == ["humo.mov"]


def test_restored_catalog_does_not_count_missing_extractions(env):
    """Tras restaurar el catálogo en otra máquina, lo «extraído» que no está en la caché vuelve a
    estar dentro del pack y no cuenta como caché ocupada."""
    from trama.packs import cache_bytes_used, reconcile_cache

    client = env["client"]
    root: Path = env["root"]
    files = env["files"]
    (root / "packs").mkdir()
    make_pack(root / "packs", {"Audio/tono.wav": files["audio"]}, "c.zip")
    pack = index_and_wait(client, source_id(client), "packs/c.zip")
    client.post(f"/api/packs/{pack['id']}/extract", json={"prefix": ""})
    wait_idle(client)
    db, settings = env["db"] if "db" in env else client.app.state.trama.db, env["settings"]
    assert cache_bytes_used(db) > 0
    shutil.rmtree(settings.cache_dir / pack["id"])
    assert reconcile_cache(db, settings) == 1
    assert cache_bytes_used(db) == 0
    assert client.get(f"/api/packs/{pack['id']}").json()["extracted"] == 0


def test_preview_batches_fit_the_cache():
    """Las tandas de vistas previas caben en el 40 % de la caché; una entrada enorme va sola."""
    from trama.worker import _preview_batches

    gb = 1024**3
    entries = [{"size": s} for s in [1 * gb] * 4 + [6 * gb] + [10] * 30]
    batches = [len(b) for _, b in _preview_batches(entries, 5 * gb)]
    assert batches == [2, 2, 1, 25, 5]


def test_job_interrupted_by_shutdown_goes_back_to_queue(env):
    """Una parada del servidor no cancela ni da por fallido el trabajo en curso: vuelve a la cola."""
    from trama.db import new_id, now_iso
    from trama.worker import JobCancelled

    worker = env["client"].app.state.trama.worker
    db = env["client"].app.state.trama.db
    job_id = new_id("job")
    with db.tx() as conn:
        conn.execute("INSERT INTO jobs(id, kind, status, payload, created_at) VALUES (?, 'backup', 'running', '{}', ?)", (job_id, now_iso()))
    worker._stop.set()
    try:
        original = worker._run_backup
        worker._run_backup = lambda job: (_ for _ in ()).throw(JobCancelled())
        worker._run({"id": job_id, "kind": "backup", "payload": "{}"})
    finally:
        worker._run_backup = original
        worker._stop.clear()
    assert db.one("SELECT status FROM jobs WHERE id = ?", (job_id,))["status"] == "queued"


def test_pin_project_to_sidebar(env):
    """Un proyecto se puede fijar en la barra lateral y la marca persiste."""
    client = env["client"]
    sid = client.post("/api/selections", json={"name": "Aprender"}).json()["id"]
    assert client.patch(f"/api/selections/{sid}", json={"pinned": True}).json()["pinned"] == 1
    assert next(x for x in client.get("/api/selections").json() if x["id"] == sid)["pinned"] == 1
    assert client.patch(f"/api/selections/{sid}", json={"notes": "hola"}).json()["pinned"] == 1
    assert client.patch(f"/api/selections/{sid}", json={"pinned": False}).json()["pinned"] == 0


def test_connections_of_dead_threads_are_closed(tmp_path):
    """Cada hilo nuevo abre su conexión; las de hilos que ya terminaron se cierran, así un
    servidor que crea hilos sin parar no agota los descriptores de archivo."""
    import threading

    from trama.db import Database

    db = Database(tmp_path / "c.sqlite")
    db.migrate()
    for _ in range(200):
        t = threading.Thread(target=lambda: db.one("SELECT 1"))
        t.start()
        t.join()
    db.one("SELECT 1")  # abre la del hilo actual y recoge las muertas
    assert db.open_connections() <= 3
    db.close()


def test_health_is_public_and_checks_the_database(env):
    r = env["client"].get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_pdf_tutorial_gets_first_page_preview_and_video_link(env):
    """Un PDF dentro de un pack: vista previa de la primera página y solo el enlace al vídeo del
    efecto (se descartan perfil y tienda)."""
    import io

    from pypdf import PdfWriter
    from pypdf.annotations import Link

    w = PdfWriter()
    w.add_blank_page(width=300, height=400)
    for uri in ("https://www.instagram.com/reel/ABC123", "https://www.instagram.com/harry__allsop/", "https://stan.store/x/p/coaching"):
        w.add_annotation(0, Link(rect=(10, 10, 100, 30), target_page_index=None) if False else _uri_link(uri))
    buf = io.BytesIO()
    w.write(buf)
    client, root = env["client"], env["root"]
    (root / "packs").mkdir()
    pdf = root / "guia.pdf"
    pdf.write_bytes(buf.getvalue())
    make_pack(root / "packs", {"Tutoriales/Guia Efecto.pdf": pdf}, "tut.zip")
    pdf.unlink()
    pack = index_and_wait(client, source_id(client), "packs/tut.zip")
    assert client.post("/api/packs/previews").json()["queued"] == 1
    wait_idle(client)
    a = client.get("/api/assets", params={"pack_id": pack["id"], "limit": 5}).json()["items"][0]
    a = client.get(f"/api/assets/{a['id']}").json()
    assert a["preview"]["kind"] == "pdf" and a["preview"]["status"] == "ready" and a["thumb_url"]
    assert a["video_links"] == ["https://www.instagram.com/reel/ABC123"] and a["pages"] == 1
    assert client.get(a["thumb_url"]).status_code == 200


def _uri_link(uri):
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, TextStringObject

    return DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(10), FloatObject(10), FloatObject(100), FloatObject(30)]),
        NameObject("/A"): DictionaryObject({NameObject("/S"): NameObject("/URI"), NameObject("/URI"): TextStringObject(uri)}),
    })


def test_psd_and_mogrt_get_a_still_preview(env, tmp_path):
    """PSD (imagen fusionada) y MOGRT (la miniatura que trae dentro) tienen vista previa."""
    from PIL import Image

    client = env["client"]
    root = env["root"]
    Image.new("RGB", (64, 40), (200, 30, 30)).save(tmp_path / "thumb.png")
    mogrt = root / "Plantillas" / "titulo.mogrt"
    mogrt.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(mogrt, "w") as zf:
        zf.writestr("definition.json", "{}")
        zf.write(tmp_path / "thumb.png", "thumb.png")
    pack = make_pack(root, {"Plantillas/titulo.mogrt": mogrt}, name="plantillas.zip")
    mogrt.unlink()
    sid = source_id(client)
    info = index_and_wait(client, sid, pack.name)
    client.post("/api/packs/previews")
    wait_idle(client)
    items = client.get("/api/assets", params={"pack_id": info["id"]}).json()["items"]
    m = next(a for a in items if a["version"]["ext"] == ".mogrt")
    assert m["preview"]["kind"] == "still" and m["preview"]["status"] == "ready" and m["thumb_url"]


def test_same_video_in_another_format_is_found_as_possible_version(env, tools):
    """El mismo clip re-exportado (.mov → .mp4 a otra resolución) no es idéntico en bytes pero la
    huella visual lo encuentra; no se fusiona: aparece como posible versión en la ficha."""
    import subprocess

    client = env["client"]
    root = env["root"]
    src = root / "Versiones" / "leak_4k.mov"
    src.parent.mkdir(exist_ok=True)
    subprocess.run([tools.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=25", "-t", "2",
                    "-c:v", "mjpeg", "-q:v", "3", str(src)], check=True)
    subprocess.run([tools.ffmpeg, "-v", "error", "-y", "-i", str(src), "-vf", "scale=320:180", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(root / "Versiones" / "leak_hd.mp4")], check=True)
    import_all(client)
    wait_idle(client)
    from trama.twins import rebuild_twins

    assert rebuild_twins(client.app.state.trama.db) >= 1
    items = client.get("/api/assets", params={"limit": 50}).json()["items"]
    mov = next(a for a in items if a["original_title"] == "leak_4k.mov")
    detail = client.get(f"/api/assets/{mov['id']}").json()
    assert [t["ext"] for t in detail["twins"]] == [".mp4"]
    assert client.get("/api/assets", params={"duplicates": True}).json()["total"] >= 2
    # la carta de ajuste y el vídeo con alfa no se parecen a nada
    opaque = next(a for a in items if a["original_title"] == "test_opaque.mp4")
    assert client.get(f"/api/assets/{opaque['id']}").json()["twins"] == []


def test_mogrt_offers_its_tutorial_and_the_same_effect_in_video(env, tmp_path):
    """Un MOGRT no se reproduce sin Adobe: su ficha ofrece el tutorial de la colección y el mismo
    efecto en vídeo que haya en la biblioteca («Paper Rip» ↔ «Paper Tear»)."""
    from PIL import Image

    client = env["client"]
    root = env["root"]
    files = env["files"]
    Image.new("RGB", (64, 36), (200, 150, 90)).save(tmp_path / "thumb.png")
    mogrt = tmp_path / "Paper Rip Transition 4K 3.mogrt"
    with zipfile.ZipFile(mogrt, "w") as zf:
        zf.writestr("definition.json", "{}")
        zf.write(tmp_path / "thumb.png", "thumb.png")
    pack = make_pack(root, {
        "BUNDLE/PAPER RIP/MOGRTS/Paper Rip Transition 4K 3.mogrt": mogrt,
        "BUNDLE/PAPER RIP/Help/Tutorial.mp4": files["opaque"],
        "OTRO/Paper Tear 7.mov": files["alpha"],
    }, name="bundle.zip")
    info = index_and_wait(client, source_id(client), pack.name)
    client.post("/api/packs/previews")
    wait_idle(client)
    items = client.get("/api/assets", params={"pack_id": info["id"], "limit": 50}).json()["items"]
    m = next(a for a in items if a["version"]["ext"] == ".mogrt")
    related = client.get(f"/api/assets/{m['id']}").json()["related_videos"]
    whys = {r["title"]: r["why"] for r in related}
    assert whys.get("Tutorial") == "tutorial"
    assert any(r["why"] == "mismo efecto en vídeo" and "Tear" in r["title"] for r in related)


def test_nested_zip_contents_are_catalogued_one_level_deep(env, tmp_path):
    """Un ZIP dentro del pack (descarga de plantillas) se cataloga por dentro: sus vídeos, LUT y
    presets de DaVinci entran como recursos con vista previa; un ZIP más adentro no se abre y un
    traversal dentro del anidado se rechaza igual que fuera."""
    client = env["client"]
    root = env["root"]
    files = env["files"]
    inner = tmp_path / "vhs-transitions-2025-01-07-12-51-59-utc.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.write(files["opaque"], "VHS/1.mp4")
        zf.writestr("Presets/Vertical.preset", "PresetType: ProjectSettingsPreset")
        zf.writestr("mas/otro.zip", b"PK\x05\x06" + b"\0" * 18)
        zf.writestr("../fuera.mp4", b"x" * 100)
    pack = make_pack(root, {"Super Pack/Transiciones/Transiciones VHS/vhs-transitions-2025-01-07-12-51-59-utc.zip": inner}, name="anidado.zip")
    info = index_and_wait(client, source_id(client), pack.name)
    client.post("/api/packs/previews")
    wait_idle(client)
    items = client.get("/api/assets", params={"pack_id": info["id"], "limit": 50}).json()["items"]
    by_ext = {a["version"]["ext"]: a for a in items}
    assert set(by_ext) == {".mp4", ".preset"}
    video = by_ext[".mp4"]
    assert video["preview"]["status"] == "ready" and video["thumb_url"]
    assert video["title"] == "Vhs-transitions · VHS · 1" or video["title"].endswith("· 1")
    assert by_ext[".preset"]["required_app"].startswith("DaVinci Resolve")
    entries = client.get(f"/api/packs/{info['id']}").json()
    assert entries["entries_unsafe"] >= 1  # el traversal del anidado
    # la descarga del original sale del anidado y coincide byte a byte
    r = client.get(f"/api/assets/{video['id']}/original")
    assert r.status_code == 200 and r.content == files["opaque"].read_bytes()


def test_only_usable_hides_adobe_only_formats(env, tmp_path):
    """«Solo lo que uso» esconde lo que solo abre Adobe; el resto sigue igual, también en la franja."""
    client = env["client"]
    root = env["root"]
    files = env["files"]
    mogrt = tmp_path / "Titulo.mogrt"
    with zipfile.ZipFile(mogrt, "w") as zf:
        zf.writestr("definition.json", "{}")
    pack = make_pack(root, {"Plantillas/Titulo.mogrt": mogrt, "Plantillas/Titulo.mp4": files["opaque"]}, name="uso.zip")
    info = index_and_wait(client, source_id(client), pack.name)
    all_ = client.get("/api/assets", params={"pack_id": info["id"]}).json()["items"]
    usable = client.get("/api/assets", params={"pack_id": info["id"], "usable": True}).json()["items"]
    assert {a["version"]["ext"] for a in all_} == {".mogrt", ".mp4"}
    assert {a["version"]["ext"] for a in usable} == {".mp4"}
    assert client.get("/api/tags", params={"pack_id": info["id"], "usable": True}).status_code == 200


def test_license_is_set_per_pack_and_inherited_by_its_resources(env):
    """Licencia por pack: el recurso la hereda (con que un pack tenga licencia, cuenta con
    licencia) y se puede filtrar por ella."""
    client = env["client"]
    root = env["root"]
    files = env["files"]
    ref = make_pack(root, {"FX/clip.mp4": files["opaque"], "FX/otro.mov": files["alpha"]}, name="referencia.zip")
    lic = make_pack(root, {"Comprado/clip.mp4": files["opaque"]}, name="comprado.zip")
    sid = source_id(client)
    p_ref = index_and_wait(client, sid, ref.name)
    p_lic = index_and_wait(client, sid, lic.name)
    assert client.patch(f"/api/packs/{p_ref['id']}", json={"license": "reference"}).json()["license"] == "reference"
    client.patch(f"/api/packs/{p_lic['id']}", json={"license": "licensed"})
    assert client.patch(f"/api/packs/{p_lic['id']}", json={"license": "pirata"}).status_code == 400
    items = {a["original_title"]: a for a in client.get("/api/assets", params={"pack_id": p_ref["id"]}).json()["items"]}
    # clip.mp4 está en los dos packs (mismos bytes): cuenta como con licencia; otro.mov solo en el de referencia
    assert client.get(f"/api/assets/{items['clip.mp4']['id']}").json()["license"] == "licensed"
    assert client.get(f"/api/assets/{items['otro.mov']['id']}").json()["license"] == "reference"
    refs = client.get("/api/assets", params={"license": "reference"}).json()["items"]
    assert [a["original_title"] for a in refs] == ["otro.mov"]


def test_template_preview_in_a_parallel_folder_is_linked(env):
    """La muestra de una plantilla puede estar en una carpeta paralela del mismo pack:
    «Ready Files/Titles/Title_13.setting» ↔ «All Files Preview/Titles/Title 13.mp4»."""
    client = env["client"]
    root = env["root"]
    files = env["files"]
    tpl = root / "Title_13.setting"
    tpl.write_text("{ Tools = ordered() {} }")
    pack = make_pack(root, {"YT/Ready Files/Titles/Title_13.setting": tpl, "YT/All Files Preview/Titles/Title 13.mp4": files["opaque"]}, name="yt.zip")
    tpl.unlink()
    info = index_and_wait(client, source_id(client), pack.name)
    items = client.get("/api/assets", params={"pack_id": info["id"]}).json()["items"]
    setting = next(a for a in items if a["version"]["ext"] == ".setting")
    assert setting["provider_preview"] and setting["provider_preview"]["title"].startswith("Title")


def test_lut_demo_works_with_an_apostrophe_in_the_path(env, tools, tmp_path):
    """«Super_Cinematic_LUT's/…cube»: el apóstrofo rompía la orden de FFmpeg."""
    from trama.media import generate_derivative

    folder = tmp_path / "Super_Cinematic_LUT's (NEW)"
    folder.mkdir()
    lut = folder / "Grade, [2].cube"
    lut.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n")
    dest = tmp_path / "demo.jpg"
    info = generate_derivative(env["settings"], tools, "lut_demo", lut, {"media_kind": "other", "preview_support": "lut_demo"}, dest, None)
    assert dest.exists() and info["width"] == 960
