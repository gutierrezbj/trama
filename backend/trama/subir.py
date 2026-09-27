"""Sube packs a la carpeta TRAMA/Packs de Google Drive desde este equipo, sin catalogarlos aquí.

Acepta ZIP sueltos o un «ZIP de ZIPs» (como las descargas «Download all» de las tiendas): de este
último saca cada ZIP interior de uno en uno a una carpeta temporal, lo sube reanudable, verifica
md5 contra Google y borra la copia temporal. Los que ya están en Drive (mismo md5) se saltan, así
los repetidos no se suben dos veces. Los PDF (guías, licencias) van a TRAMA/Documentos.
Después, en TRAMA: «Fuentes y packs» → «Buscar packs nuevos en Drive».
"""
from __future__ import annotations

import shutil
import sys
import time
import zipfile
from pathlib import Path

from .config import Settings
from .drive import DriveClient, md5_of, mime_for
from .packs import decode_name


def _fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _upload(client: DriveClient, path: Path, name: str, folder_id: str, known_md5: set[str]) -> str:
    md5 = md5_of(path)
    if md5 in known_md5:
        return f"ya estaba en Drive (mismo md5): {name}"
    size = path.stat().st_size
    session = client.start_upload(name, size, mime_for(path.suffix.lower()), folder_id, {"trama": "pack"})
    started, last = time.time(), [0.0]

    def progress(done: int) -> None:
        now = time.time()
        if now - last[0] >= 5 or done >= size:
            last[0] = now
            rate = done / max(1e-6, now - started)
            print(f"   {name}: {_fmt(done)} de {_fmt(size)} ({_fmt(rate)}/s)", flush=True)

    meta = client.upload_file(path, session, size, 0, progress)
    if meta.get("md5Checksum") != md5:
        client.delete_file(meta["id"])
        raise RuntimeError(f"md5 distinto tras subir {name}; se borró la copia remota")
    known_md5.add(md5)
    return f"subido y verificado: {name} ({_fmt(size)})"


def run(settings: Settings, sources: list[Path], transport=None) -> int:
    client = DriveClient(settings, transport)
    try:
        root = client.ensure_folder()
        packs_folder = client.ensure_subfolder("Packs", root)
        docs_folder = client.ensure_subfolder("Documentos", root)
        known_md5 = {f["md5Checksum"] for fid in (packs_folder, docs_folder) for f in client.list_children(fid) if f.get("md5Checksum")}
        tmp_dir = settings.data_dir / "subida-temporal"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        failures = 0
        for src in sources:
            print(f"== {src.name}", flush=True)
            with zipfile.ZipFile(src) as outer:
                inner = [i for i in outer.infolist() if not i.is_dir()]
                zips = [i for i in inner if decode_name(i).lower().endswith(".zip")]
                containers = [i for i in inner if decode_name(i).lower().endswith((".zip", ".pdf"))]
                # Solo es «ZIP de ZIPs» si dentro hay ZIP de verdad; un ZIP de PDF es un pack normal.
                if not zips or len(containers) < len(inner) // 2:
                    # ZIP normal (recursos dentro): se sube tal cual.
                    containers = []
            items = [(src, None)] if not containers else [(src, i) for i in containers]
            for container, info in items:
                name = Path(decode_name(info).replace("\\", "/")).name if info else src.name
                folder = docs_folder if name.lower().endswith(".pdf") else packs_folder
                try:
                    if info is None:
                        print(" -", _upload(client, src, name, folder, known_md5), flush=True)
                        continue
                    tmp = tmp_dir / name
                    with zipfile.ZipFile(container) as outer, outer.open(info) as fin, open(tmp, "wb") as fout:
                        shutil.copyfileobj(fin, fout, 8 * 1024 * 1024)
                    try:
                        print(" -", _upload(client, tmp, name, folder, known_md5), flush=True)
                    finally:
                        tmp.unlink(missing_ok=True)
                except Exception as exc:  # sigue con el resto; al volver a ejecutar se reintenta
                    failures += 1
                    print(f" ! {name}: {exc}", flush=True)
        print("Hecho." + (f" {failures} con error: vuelve a ejecutar para reintentarlos." if failures else " Ahora en TRAMA: «Buscar packs nuevos en Drive»."))
        return 1 if failures else 0
    finally:
        client.close()


if __name__ == "__main__":  # pragma: no cover
    from .config import load_settings

    sys.exit(run(load_settings(), [Path(a) for a in sys.argv[1:]]))
