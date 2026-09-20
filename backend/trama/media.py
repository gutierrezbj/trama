"""Análisis y derivados multimedia con FFmpeg/ffprobe y Pillow.

Todo dato devuelto por `probe_file` procede de una medición real. Cuando algo no puede
medirse se devuelve None (la interfaz lo muestra como pendiente o desconocido), nunca 0.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageOps

from .config import Settings, media_kind_for

RECIPES = {
    "thumb": "thumb-v1",
    "proxy": "proxy-v1",
    "proxy_dark": "proxy-bg-v1",
    "proxy_light": "proxy-bg-v1",
    "proxy_checker": "proxy-bg-v1",
    "waveform": "waveform-v1",
    "audio_proxy": "audio-proxy-v1",
}

BG_COLORS = {"dark": "#141618", "light": "#F2F0E9"}
CHECKER_COLORS = ((0x3C, 0x41, 0x47), (0x56, 0x5C, 0x63))

# Formatos de píxel con canal alfa (lista explícita; lo desconocido se reporta como None).
ALPHA_PIX_PREFIXES = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16", "ayuv", "vuya", "rgbaf", "bgraf", "gbrapf")


class MediaError(RuntimeError):
    pass


@dataclass
class Tools:
    ffmpeg: str
    ffprobe: str
    ffmpeg_version: str
    ffprobe_version: str


_tools_cache: Tools | None = None
_tools_lock = threading.Lock()


def resolve_tools(settings: Settings) -> Tools:
    global _tools_cache
    with _tools_lock:
        if _tools_cache is not None:
            return _tools_cache
        ffmpeg = settings.ffmpeg or shutil.which("ffmpeg")
        ffprobe = settings.ffprobe or shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            try:
                from static_ffmpeg import run as static_run  # type: ignore

                s_ffmpeg, s_ffprobe = static_run.get_or_fetch_platform_executables_else_raise()
                ffmpeg = ffmpeg or s_ffmpeg
                ffprobe = ffprobe or s_ffprobe
            except Exception as exc:  # pragma: no cover - depende del entorno
                raise MediaError(f"FFmpeg/ffprobe no disponibles: {exc}") from exc

        def version_of(binary: str) -> str:
            try:
                out = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=20)
                return (out.stdout or out.stderr).splitlines()[0].strip()
            except Exception as exc:
                return f"no ejecutable ({exc})"

        _tools_cache = Tools(ffmpeg, ffprobe, version_of(ffmpeg), version_of(ffprobe))
        return _tools_cache


def _run(cmd: list[str], timeout: int, register=None) -> subprocess.CompletedProcess:
    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags
    )
    if register:
        register(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise MediaError(f"Tiempo agotado ({timeout}s): {' '.join(cmd[:3])}")
    finally:
        if register:
            register(None)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _as_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fps(value: str | None) -> float | None:
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        return round(float(Fraction(value)), 3)
    except (ValueError, ZeroDivisionError):
        return None


def _rotation(stream: dict) -> int:
    rotation = 0
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rotation = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    tags = stream.get("tags") or {}
    if not rotation and tags.get("rotate"):
        try:
            rotation = int(tags["rotate"])
        except ValueError:
            pass
    return rotation % 360


def _orientation(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    if width == height:
        return "square"
    return "horizontal" if width > height else "vertical"


def pix_fmt_has_alpha(pix_fmt: str | None) -> bool | None:
    if not pix_fmt:
        return None
    if pix_fmt.startswith(ALPHA_PIX_PREFIXES):
        return True
    if pix_fmt == "pal8":
        return None  # paleta: puede o no tener transparencia; no se afirma
    return False


def measure_alpha_usage(tools: Tools, path: Path, timeout: int, register=None) -> bool | None:
    """Mide si el canal alfa se usa realmente (algún píxel no opaco) en hasta 6 fotogramas."""
    cmd = [
        tools.ffmpeg, "-v", "error", "-i", str(path),
        "-vf", "select='not(mod(n,7))',alphaextract,scale=96:96",
        "-frames:v", "6", "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        proc = _run(cmd, timeout, register)
    except MediaError:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return min(proc.stdout) < 250


def probe_file(tools: Tools, path: Path, timeout: int, register=None) -> dict:
    kind = media_kind_for(path.suffix)
    if kind == "image":
        return _probe_image(path)
    if kind == "other":
        return {"media_kind": "other", "container": path.suffix.lower().lstrip("."), "preview_support": "none"}

    cmd = [tools.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = _run(cmd, timeout, register)
    if proc.returncode != 0:
        raise MediaError((proc.stderr or b"").decode("utf-8", "replace").strip() or "ffprobe falló")
    data = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    result: dict = {
        "media_kind": kind,
        "container": fmt.get("format_name"),
        "duration_s": _as_float(fmt.get("duration")),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "video": None,
        "audio": None,
    }
    if video is not None:
        width, height = video.get("width"), video.get("height")
        rotation = _rotation(video)
        disp_w, disp_h = (height, width) if rotation in (90, 270) else (width, height)
        nb_frames = video.get("nb_frames")
        pix_fmt = video.get("pix_fmt")
        vd = _as_float(video.get("duration"))
        result["video"] = {
            "codec": video.get("codec_name"),
            "profile": video.get("profile"),
            "pix_fmt": pix_fmt,
            "coded_width": width,
            "coded_height": height,
            "width": disp_w,
            "height": disp_h,
            "rotation": rotation,
            "fps": _fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")),
            "frames": int(nb_frames) if str(nb_frames or "").isdigit() else None,
            "duration_s": vd,
            "alpha_format": pix_fmt_has_alpha(pix_fmt),
            "alpha_used": None,
        }
        if result["duration_s"] is None:
            result["duration_s"] = vd
        result["orientation"] = _orientation(disp_w, disp_h)
        if result["video"]["alpha_format"]:
            result["video"]["alpha_used"] = measure_alpha_usage(tools, path, timeout, register)
        # MJPEG dentro de MOV y similares: es vídeo aunque el códec sea "de imagen".
        if kind == "audio":
            result["media_kind"] = "video"
    if audio is not None:
        bits = audio.get("bits_per_raw_sample") or audio.get("bits_per_sample")
        result["audio"] = {
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio["sample_rate"]) if str(audio.get("sample_rate", "")).isdigit() else None,
            "channels": audio.get("channels"),
            "bits": int(bits) if str(bits or "").isdigit() and int(bits) > 0 else None,
            "duration_s": _as_float(audio.get("duration")),
        }
        if result["duration_s"] is None:
            result["duration_s"] = result["audio"]["duration_s"]
    if video is None and audio is None:
        raise MediaError("El archivo no contiene flujos de vídeo ni de audio reconocibles")
    return result


def _probe_image(path: Path) -> dict:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im) or im
        mode = im.mode
        alpha = mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in im.info)
        alpha_used: bool | None = None
        if alpha:
            small = im.convert("RGBA").resize((96, 96))
            alpha_used = min(small.getchannel("A").getdata()) < 250
        return {
            "media_kind": "image",
            "container": (im.format or path.suffix.lstrip(".")).lower(),
            "duration_s": None,
            "video": None,
            "audio": None,
            "image": {"mode": mode, "width": im.width, "height": im.height, "alpha_format": bool(alpha), "alpha_used": alpha_used},
            "orientation": _orientation(im.width, im.height),
        }


# --------------------------------------------------------------------------- derivados

def plan_derivatives(analysis: dict) -> list[str]:
    kind = analysis.get("media_kind")
    if kind == "video":
        v = analysis.get("video") or {}
        if v.get("alpha_format") and v.get("alpha_used") is not False:
            return ["thumb", "proxy_dark", "proxy_light", "proxy_checker"]
        return ["thumb", "proxy"]
    if kind == "audio":
        return ["waveform", "audio_proxy"]
    if kind == "image":
        return ["thumb"]
    return []


def derivative_filename(kind: str) -> str:
    return {
        "thumb": "thumb.jpg",
        "proxy": "proxy.mp4",
        "proxy_dark": "proxy_dark.mp4",
        "proxy_light": "proxy_light.mp4",
        "proxy_checker": "proxy_checker.mp4",
        "waveform": "waveform.png",
        "audio_proxy": "audio.m4a",
    }[kind]


def derivative_mime(kind: str) -> str:
    return {
        "thumb": "image/jpeg",
        "proxy": "video/mp4",
        "proxy_dark": "video/mp4",
        "proxy_light": "video/mp4",
        "proxy_checker": "video/mp4",
        "waveform": "image/png",
        "audio_proxy": "audio/mp4",
    }[kind]


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def scaled_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    if width <= max_width:
        return _even(width), _even(height)
    new_h = int(round(height * max_width / width))
    return _even(max_width), _even(max(2, new_h))


def checker_image(settings: Settings, width: int, height: int, tile: int = 24) -> Path:
    bg_dir = settings.derivatives_dir / "_bg"
    bg_dir.mkdir(parents=True, exist_ok=True)
    path = bg_dir / f"checker_{width}x{height}.png"
    if path.exists():
        return path
    img = Image.new("RGB", (width, height), CHECKER_COLORS[0])
    px = img.load()
    for y in range(height):
        for x in range(width):
            if ((x // tile) + (y // tile)) % 2:
                px[x, y] = CHECKER_COLORS[1]
    img.save(path)
    return path


def generate_derivative(
    settings: Settings, tools: Tools, kind: str, source: Path, analysis: dict, dest: Path, register=None
) -> dict:
    """Genera un derivado y devuelve {width,height} medidos del resultado cuando aplica."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    timeout = settings.ffmpeg_timeout
    media_kind = analysis.get("media_kind")
    video = analysis.get("video") or {}
    duration = analysis.get("duration_s") or 0

    if kind == "thumb" and media_kind == "image":
        with Image.open(source) as im:
            im = ImageOps.exif_transpose(im) or im
            im = im.convert("RGBA")
            im.thumbnail((settings.thumb_max_width, settings.thumb_max_width * 4))
            bg = Image.open(checker_image(settings, im.width, im.height)).convert("RGBA")
            bg.alpha_composite(im)
            bg.convert("RGB").save(tmp, format="JPEG", quality=86)
        tmp.replace(dest)
        return {"width": bg.width, "height": bg.height}

    if kind == "thumb":
        w, h = scaled_size(video.get("width") or 640, video.get("height") or 360, settings.thumb_max_width)
        seek = max(0.0, min(duration * 0.35, max(duration - 0.05, 0)))
        alpha = bool(video.get("alpha_format"))
        if alpha:
            checker = checker_image(settings, w, h)
            cmd = [tools.ffmpeg, "-v", "error", "-y", "-ss", f"{seek:.3f}", "-i", str(source), "-i", str(checker),
                   "-filter_complex", f"[0:v]scale={w}:{h},format=rgba[fg];[1:v][fg]overlay=format=auto",
                   "-frames:v", "1", "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", str(tmp)]
        else:
            cmd = [tools.ffmpeg, "-v", "error", "-y", "-ss", f"{seek:.3f}", "-i", str(source),
                   "-vf", f"scale={w}:{h}", "-frames:v", "1", "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", str(tmp)]
        _ffmpeg(cmd, timeout, register, tmp, dest)
        return {"width": w, "height": h}

    if kind == "proxy":
        w, h = scaled_size(video.get("width") or 640, video.get("height") or 360, settings.proxy_max_width)
        cmd = [tools.ffmpeg, "-v", "error", "-y", "-i", str(source),
               "-vf", f"scale={w}:{h},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-movflags", "+faststart"]
        if analysis.get("audio"):
            cmd += ["-c:a", "aac", "-b:a", "96k", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += ["-f", "mp4", str(tmp)]
        _ffmpeg(cmd, timeout, register, tmp, dest)
        return {"width": w, "height": h}

    if kind in ("proxy_dark", "proxy_light", "proxy_checker"):
        w, h = scaled_size(video.get("width") or 640, video.get("height") or 360, settings.proxy_max_width)
        fps = video.get("fps") or 30
        if kind == "proxy_checker":
            bg_input = ["-loop", "1", "-framerate", str(fps), "-i", str(checker_image(settings, w, h))]
        else:
            color = BG_COLORS["dark" if kind == "proxy_dark" else "light"]
            bg_input = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}"]
        cmd = [tools.ffmpeg, "-v", "error", "-y", "-i", str(source), *bg_input,
               "-filter_complex", f"[0:v]scale={w}:{h},format=rgba[fg];[1:v][fg]overlay=shortest=1:format=auto,format=yuv420p",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-movflags", "+faststart"]
        if analysis.get("audio"):
            cmd += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += ["-f", "mp4", str(tmp)]
        _ffmpeg(cmd, timeout, register, tmp, dest)
        return {"width": w, "height": h}

    if kind == "waveform":
        w, h = 1200, 220
        cmd = [tools.ffmpeg, "-v", "error", "-y", "-i", str(source),
               "-filter_complex", f"aformat=channel_layouts=mono,showwavespic=s={w}x{h}:colors=#E8BE46:scale=sqrt",
               "-frames:v", "1", "-f", "image2", "-c:v", "png", str(tmp)]
        _ffmpeg(cmd, timeout, register, tmp, dest)
        return {"width": w, "height": h}

    if kind == "audio_proxy":
        cmd = [tools.ffmpeg, "-v", "error", "-y", "-i", str(source), "-vn", "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", "-f", "mp4", str(tmp)]
        _ffmpeg(cmd, timeout, register, tmp, dest)
        return {}

    raise MediaError(f"Derivado no soportado: {kind}")


def _ffmpeg(cmd: list[str], timeout: int, register, tmp: Path, dest: Path) -> None:
    proc = _run(cmd, timeout, register)
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        if tmp.exists():
            tmp.unlink()
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise MediaError(err.splitlines()[-1] if err else f"ffmpeg devolvió {proc.returncode}")
    tmp.replace(dest)
