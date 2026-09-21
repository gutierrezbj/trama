"""Acceso privado: contraseña única del propietario, sesión firmada en cookie y tokens portadores.

- `TRAMA_AUTH_MODE=off` (por defecto): sin autenticación; solo aceptable ligado a loopback.
- `TRAMA_AUTH_MODE=password`: toda la API (catálogo, previews, originales, packs…) exige sesión.
  La contraseña se guarda como PBKDF2-SHA256 (`python -m trama set-password`).
- La cookie es HttpOnly + SameSite=Strict (+ Secure detrás de HTTPS) y va firmada con HMAC sobre
  un secreto generado en el directorio de datos. Un token portador (`Authorization: Bearer …`)
  sirve para integraciones sin navegador (E4).
- Intentos fallidos: bloqueo progresivo por IP, persistente en la base de datos.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings
from .db import Database, now_iso

COOKIE_NAME = "trama_session"
PUBLIC_PATHS = {"/api/auth/status", "/api/auth/login", "/api/drive/auth/callback"}
PBKDF2_ITERATIONS = 310_000


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iterations, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def load_secret(settings: Settings) -> bytes:
    path = settings.secret_file
    if path.is_file():
        data = path.read_bytes().strip()
        if len(data) >= 32:
            return data
    secret = secrets.token_bytes(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(secret: bytes, hours: int) -> str:
    payload = json.dumps({"exp": int(time.time()) + hours * 3600, "nonce": secrets.token_hex(8)}, separators=(",", ":")).encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def verify_session(secret: bytes, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _unb64(payload_b64)
        expected = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            return False
        data = json.loads(payload)
        return int(data.get("exp", 0)) > time.time()
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


class LoginGuard:
    """Bloqueo progresivo por IP: 5 fallos → 1 min, luego se duplica hasta 1 h."""

    def __init__(self, db: Database):
        self.db = db

    def blocked_for(self, ip: str) -> int:
        row = self.db.one("SELECT failures, blocked_until FROM auth_attempts WHERE ip = ?", (ip,))
        if row is None or not row["blocked_until"]:
            return 0
        until = datetime.fromisoformat(row["blocked_until"])
        remaining = (until - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    def register_failure(self, ip: str) -> int:
        row = self.db.one("SELECT failures FROM auth_attempts WHERE ip = ?", (ip,))
        failures = (row["failures"] if row else 0) + 1
        blocked_until = None
        if failures >= 5:
            minutes = min(60, 2 ** (failures - 5))
            blocked_until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO auth_attempts(ip, failures, blocked_until) VALUES (?, ?, ?) ON CONFLICT(ip) DO UPDATE SET failures = excluded.failures, blocked_until = excluded.blocked_until",
                (ip, failures, blocked_until),
            )
        return failures

    def reset(self, ip: str) -> None:
        with self.db.tx() as conn:
            conn.execute("DELETE FROM auth_attempts WHERE ip = ?", (ip,))


def is_authenticated(settings: Settings, secret: bytes, cookie: str | None, authorization: str | None) -> bool:
    if settings.auth_mode != "password":
        return True
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        return any(hmac.compare_digest(token, t) for t in settings.api_tokens)
    return verify_session(secret, cookie)


def auth_status(settings: Settings) -> dict:
    return {
        "mode": settings.auth_mode,
        "password_set": bool(settings.password_hash),
        "cookie_secure": settings.cookie_secure,
        "misconfigured": settings.auth_mode == "password" and not settings.password_hash,
    }


__all__ = [
    "COOKIE_NAME", "PUBLIC_PATHS", "LoginGuard", "auth_status", "hash_password", "is_authenticated",
    "load_secret", "sign_session", "verify_password", "verify_session", "now_iso", "Path",
]
