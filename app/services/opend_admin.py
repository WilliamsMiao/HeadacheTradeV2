from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

SENSITIVE_KEYS = {"login_password", "trd_unlock_password", "FUTU_LOGIN_PASSWORD", "FUTU_TRD_UNLOCK_PASSWORD"}


@dataclass
class AdminResult:
    ok: bool
    message: str
    data: dict[str, Any]


def opend_socket_health() -> dict[str, object]:
    settings = get_settings()
    host = settings.futu_host
    port = settings.futu_port
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return {"status": "ok", "host": host, "port": port, "connected": True}
    except OSError as exc:
        return {"status": "error", "host": host, "port": port, "connected": False, "error": str(exc)}


def status() -> AdminResult:
    return _run_admin("status", {})


def install() -> AdminResult:
    return _run_admin("install", {})


def start() -> AdminResult:
    return _run_admin("start", {})


def stop() -> AdminResult:
    return _run_admin("stop", {})


def restart() -> AdminResult:
    return _run_admin("restart", {})


def configure(login_account: str, login_password: str, trd_unlock_password: str = "") -> AdminResult:
    return _run_admin(
        "configure",
        {
            "login_account": login_account.strip(),
            "login_password": login_password,
            "trd_unlock_password": trd_unlock_password,
        },
    )


def verify_code(kind: str, code: str) -> AdminResult:
    action = "submit-phone-code" if kind == "phone" else "submit-captcha-code"
    return _run_admin(action, {"code": code.strip()})


def _run_admin(action: str, payload: dict[str, Any]) -> AdminResult:
    command = os.getenv("OPEND_ADMIN_COMMAND", "sudo /usr/local/sbin/headachetrade-opend-admin").split()
    try:
        completed = subprocess.run(
            [*command, action],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=60 if action != "install" else 600,
            check=False,
        )
    except FileNotFoundError:
        return AdminResult(False, "OpenD 运维助手未安装", {"action": action})
    except subprocess.TimeoutExpired:
        return AdminResult(False, "OpenD 运维操作超时", {"action": action})

    stdout = _sanitize(completed.stdout)
    stderr = _sanitize(completed.stderr)
    parsed: dict[str, Any] = {}
    if stdout.strip():
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = {"raw_output": stdout.strip()}
    ok = completed.returncode == 0 and bool(parsed.get("ok", True))
    message = str(parsed.get("message") or ("操作完成" if ok else "操作失败"))
    if stderr.strip():
        parsed["stderr"] = stderr.strip()
    parsed.setdefault("action", action)
    return AdminResult(ok, message, parsed)


def _sanitize(text: str) -> str:
    cleaned = text
    for key in SENSITIVE_KEYS:
        cleaned = cleaned.replace(key, "***")
    return cleaned
