import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models import SystemConfig

PASSWORD_HASH_KEY = "auth.password_hash"
SESSION_SECRET_KEY = "auth.session_secret"
SESSION_VERSION_KEY = "auth.session_version"
SESSION_COOKIE = "ht_session"
PBKDF2_ITERATIONS = 260_000
SESSION_DAYS = 14


def password_is_configured(session: Session) -> bool:
    return bool(_get_value(session, PASSWORD_HASH_KEY))


def setup_password(session: Session, password: str) -> None:
    if password_is_configured(session):
        raise ValueError("访问密码已经设置")
    _validate_password(password)
    _set_value(session, PASSWORD_HASH_KEY, _hash_password(password))
    _set_value(session, SESSION_SECRET_KEY, secrets.token_urlsafe(48))
    _set_value(session, SESSION_VERSION_KEY, "1")
    session.commit()


def verify_password(session: Session, password: str) -> bool:
    stored = _get_value(session, PASSWORD_HASH_KEY)
    if not stored:
        return False
    return _verify_password(password, stored)


def create_session_cookie(session: Session) -> str:
    secret = _session_secret(session)
    version = _get_value(session, SESSION_VERSION_KEY) or "1"
    payload = {
        "v": version,
        "exp": int((datetime.now(UTC) + timedelta(days=SESSION_DAYS)).timestamp()),
        "nonce": secrets.token_urlsafe(16),
    }
    payload_raw = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(secret, payload_raw)
    return f"{payload_raw}.{signature}"


def request_is_authenticated(request: Request, session: Session) -> bool:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or "." not in token:
        return False
    payload_raw, signature = token.rsplit(".", 1)
    secret = _session_secret(session)
    if not hmac.compare_digest(_sign(secret, payload_raw), signature):
        return False
    try:
        payload: dict[str, Any] = json.loads(_unb64(payload_raw).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return False
    version = _get_value(session, SESSION_VERSION_KEY) or "1"
    if str(payload.get("v")) != version:
        return False
    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return False
    return expires_at > int(datetime.now(UTC).timestamp())


def clear_cookie_kwargs() -> dict[str, object]:
    return {"key": SESSION_COOKIE, "path": "/"}


def cookie_kwargs(value: str) -> dict[str, object]:
    return {
        "key": SESSION_COOKIE,
        "value": value,
        "httponly": True,
        "samesite": "lax",
        "max_age": SESSION_DAYS * 24 * 60 * 60,
        "path": "/",
    }


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("访问密码至少需要 8 个字符")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, _b64(salt), _b64(digest))


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = _unb64(salt_raw)
        expected = _unb64(digest_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _session_secret(session: Session) -> str:
    existing = _get_value(session, SESSION_SECRET_KEY)
    if existing:
        return existing
    secret = secrets.token_urlsafe(48)
    _set_value(session, SESSION_SECRET_KEY, secret)
    session.commit()
    return secret


def _sign(secret: str, payload_raw: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _get_value(session: Session, key: str) -> str:
    row = session.scalar(select(SystemConfig).where(SystemConfig.key == key))
    return row.value if row else ""


def _set_value(session: Session, key: str, value: str) -> None:
    row = session.scalar(select(SystemConfig).where(SystemConfig.key == key))
    if row is None:
        session.add(SystemConfig(key=key, value=value))
    else:
        row.value = value
