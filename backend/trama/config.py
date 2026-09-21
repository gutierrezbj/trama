"""Configuración de TRAMA.

Prioridad: variables de entorno > archivo .env en la raíz del repositorio > valores por
defecto. Las raíces permitidas se fijan aquí; el cliente nunca envía rutas arbitrarias.
"""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi", ".mxf", ".mpg", ".mpeg"}
AUDIO_EXT = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".ogg", ".m4a", ".aac"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif", ".bmp"}
LUT_EXT = {".cube", ".3dl"}
TEMPLATE_EXT = {".mogrt", ".aep", ".prproj", ".drp", ".drfx", ".look"}
OTHER_EXT = LUT_EXT | TEMPLATE_EXT | {".pdf", ".psd", ".exr"}
MEDIA_EXTENSIONS = VIDEO_EXT | AUDIO_EXT | IMAGE_EXT | OTHER_EXT
ARCHIVE_EXT = {".zip"}

# Aplicación necesaria para abrir formatos sin preview genérica (dato declarado, no medido).
REQUIRED_APP = {
    ".mogrt": "Premiere Pro (Essential Graphics) o After Effects",
    ".aep": "After Effects",
    ".prproj": "Premiere Pro",
    ".drp": "DaVinci Resolve",
    ".drfx": "DaVinci Resolve (Fusion)",
    ".look": "Premiere Pro / SpeedGrade",
    ".cube": "LUT 3D: Premiere, Resolve, Final Cut, CapCut…",
    ".3dl": "LUT 3D: Premiere, Resolve…",
    ".psd": "Photoshop",
    ".exr": "After Effects / Nuke / Resolve",
    ".pdf": "Visor de PDF",
}

CATEGORIES = [
    "vfx", "overlays", "transiciones", "animacion", "fondos", "imagenes",
    "color", "plantillas", "audio", "documentacion", "otros",
]


def media_kind_for(ext: str) -> str:
    ext = ext.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    return "other"


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "TRAMA"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "trama"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def source_id_for(root: Path) -> str:
    """Identificador estable de una raíz permitida (insensible a mayúsculas en Windows)."""
    norm = os.path.normcase(str(Path(root).resolve()))
    return "src_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


@dataclass
class Settings:
    data_dir: Path
    allowed_roots: list[Path]
    host: str = "127.0.0.1"
    port: int = 8765
    workers: int = 2
    ffmpeg: str | None = None
    ffprobe: str | None = None
    proxy_max_width: int = 960
    thumb_max_width: int = 640
    ffmpeg_timeout: int = 600
    cache_max_bytes: int = 30 * 1024**3       # caché de extracción de packs
    min_free_bytes: int = 10 * 1024**3        # espacio libre que nunca se invade
    zip_max_entries: int = 200_000
    zip_max_entry_bytes: int = 16 * 1024**3
    zip_max_depth: int = 32
    zip_max_ratio: int = 400                  # relación descomprimido/comprimido máxima aceptada
    extract_concurrency: int = 1
    env_file: Path | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "catalogo.sqlite"

    @property
    def derivatives_dir(self) -> Path:
        return self.data_dir / "derivados"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache" / "packs"

    @property
    def inventories_dir(self) -> Path:
        return self.data_dir / "inventarios"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.derivatives_dir, self.cache_dir, self.inventories_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def source_for_id(self, source_id: str) -> Path | None:
        for root in self.allowed_roots:
            if source_id_for(root) == source_id:
                return root
        return None


def load_settings(env_file: Path | None = None, overrides: dict[str, str] | None = None) -> Settings:
    env_file = env_file or Path(os.environ.get("TRAMA_ENV_FILE", REPO_ROOT / ".env"))
    values = _read_dotenv(env_file)
    values.update({k: v for k, v in os.environ.items() if k.startswith("TRAMA_")})
    if overrides:
        values.update(overrides)

    data_dir = Path(values.get("TRAMA_DATA_DIR") or _default_data_dir()).expanduser()
    roots_raw = values.get("TRAMA_ALLOWED_ROOTS", "")
    roots = [Path(p.strip()).expanduser() for p in roots_raw.split(";") if p.strip()]

    return Settings(
        data_dir=data_dir,
        allowed_roots=roots,
        host=values.get("TRAMA_HOST", "127.0.0.1"),
        port=int(values.get("TRAMA_PORT", "8765")),
        workers=max(1, int(values.get("TRAMA_WORKERS", "2"))),
        ffmpeg=values.get("TRAMA_FFMPEG") or None,
        ffprobe=values.get("TRAMA_FFPROBE") or None,
        proxy_max_width=int(values.get("TRAMA_PROXY_MAX_WIDTH", "960")),
        thumb_max_width=int(values.get("TRAMA_THUMB_MAX_WIDTH", "640")),
        ffmpeg_timeout=int(values.get("TRAMA_FFMPEG_TIMEOUT", "600")),
        cache_max_bytes=int(float(values.get("TRAMA_CACHE_MAX_GB", "30")) * 1024**3),
        min_free_bytes=int(float(values.get("TRAMA_MIN_FREE_GB", "10")) * 1024**3),
        extract_concurrency=max(1, int(values.get("TRAMA_EXTRACT_CONCURRENCY", "1"))),
        env_file=env_file if env_file.exists() else None,
        extra=values,
    )
