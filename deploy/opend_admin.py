#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALL_SCRIPT = Path("/opt/headachetrade/current/deploy/install_futu_opend.sh")
ENV_FILE = Path("/etc/futu-opend/futu-opend.env")
OPEND_BIN = Path("/opt/futu-opend/current/FutuOpenD")
SERVICE = "futu-opend"
API_PORT = 11111
TELNET_PORT = 22222
ALLOWED = {
    "install",
    "status",
    "start",
    "stop",
    "restart",
    "configure",
    "submit-phone-code",
    "submit-captcha-code",
    "verify",
}


def main() -> int:
    if os.geteuid() != 0:
        emit(False, "OpenD 运维助手需要 root 权限", action="")
        return 1
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ALLOWED:
        emit(False, "不支持的 OpenD 操作", action=action)
        return 2
    payload = read_payload()
    try:
        if action == "install":
            result = install()
        elif action == "status":
            result = status("状态已刷新")
        elif action == "start":
            run(["systemctl", "start", SERVICE], timeout=30)
            result = status("OpenD 已启动")
        elif action == "stop":
            run(["systemctl", "stop", SERVICE], timeout=30)
            result = status("OpenD 已停止")
        elif action == "restart":
            run(["systemctl", "restart", SERVICE], timeout=30)
            result = status("OpenD 已重启")
        elif action == "configure":
            result = configure(payload)
        elif action == "submit-phone-code":
            result = submit_code("input_phone_verify_code", payload)
        elif action == "submit-captcha-code":
            result = submit_code("input_pic_verify_code", payload)
        else:
            result = status("连接已检查")
        emit(**result)
        return 0 if result["ok"] else 1
    except Exception as exc:
        emit(False, f"OpenD 操作失败：{exc}", action=action)
        return 1


def read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def install() -> dict:
    if not INSTALL_SCRIPT.exists():
        return {"ok": False, "message": "安装脚本不存在，请先完成应用部署", **status_fields()}
    completed = run(["bash", str(INSTALL_SCRIPT)], timeout=600, check=False)
    fields = status_fields()
    fields["install_output"] = tail(clean(completed.stdout + "\n" + completed.stderr), 2500)
    return {"ok": completed.returncode == 0, "message": "OpenD 安装/修复已执行", **fields}


def configure(payload: dict) -> dict:
    account = str(payload.get("login_account") or "").strip()
    password = str(payload.get("login_password") or "")
    unlock = str(payload.get("trd_unlock_password") or "")
    if not account or not password:
        return {"ok": False, "message": "Futu 登录账号和密码不能为空", **status_fields()}
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "# Managed by HeadacheTradeV2 OpenD admin.",
            f"FUTU_LOGIN_ACCOUNT={shell_quote(account)}",
            f"FUTU_LOGIN_PASSWORD={shell_quote(password)}",
            f"FUTU_TRD_UNLOCK_PASSWORD={shell_quote(unlock)}",
            "",
        ]
    )
    tmp = tempfile.NamedTemporaryFile("w", delete=False, dir=str(ENV_FILE.parent))
    try:
        tmp.write(content)
        tmp.close()
        os.chmod(tmp.name, 0o640)
        os.replace(tmp.name, ENV_FILE)
    finally:
        try:
            os.unlink(tmp.name)
        except FileNotFoundError:
            pass
    try:
        import pwd
        import grp

        uid = pwd.getpwnam("root").pw_uid
        gid = grp.getgrnam("futuopend").gr_gid
        os.chown(ENV_FILE, uid, gid)
    except KeyError:
        pass
    return {"ok": True, "message": "OpenD 登录配置已保存，请启动或重启 OpenD", **status_fields()}


def submit_code(command: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    if not code:
        return {"ok": False, "message": "验证码不能为空", **status_fields()}
    reply = telnet_command(f"{command} -code={code}")
    fields = status_fields()
    fields["telnet_reply"] = clean(reply)
    ok = "错误" not in reply and "失败" not in reply
    return {"ok": ok, "message": "验证码已提交" if ok else "验证码提交后 OpenD 仍返回错误", **fields}


def status(message: str) -> dict:
    return {"ok": True, "message": message, **status_fields()}


def status_fields() -> dict:
    active = run(["systemctl", "is-active", SERVICE], check=False).stdout.strip()
    enabled = run(["systemctl", "is-enabled", SERVICE], check=False).stdout.strip()
    opend_journal = run(["journalctl", "-u", f"{SERVICE}.service", "--since", "10 minutes ago", "--no-pager"], check=False).stdout
    app_journal = run(["journalctl", "-u", "headachetrade.service", "--since", "10 minutes ago", "--no-pager"], check=False).stdout
    combined_journal = opend_journal + "\n" + app_journal
    return {
        "installed": OPEND_BIN.exists(),
        "service_active": active,
        "service_enabled": enabled,
        "api_port_open": port_open(API_PORT),
        "telnet_port_open": port_open(TELNET_PORT),
        "credentials_configured": env_has_value("FUTU_LOGIN_ACCOUNT") and env_has_value("FUTU_LOGIN_PASSWORD"),
        "needs_phone_code": "需要手机验证码" in combined_journal,
        "needs_captcha_code": "图形验证码" in combined_journal,
        "recent_log": tail(clean(combined_journal), 3000),
    }


def telnet_command(command: str) -> str:
    with socket.create_connection(("127.0.0.1", TELNET_PORT), timeout=5) as sock:
        sock.sendall((command + "\r\n").encode("utf-8"))
        sock.settimeout(2)
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("gb18030", "replace")


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def env_has_value(key: str) -> bool:
    if not ENV_FILE.exists():
        return False
    prefix = key + "="
    for line in ENV_FILE.read_text(errors="ignore").splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip().strip("'\"")
            return bool(value)
    return False


def run(args: list[str], timeout: int = 10, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=check)


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def clean(text: str) -> str:
    cleaned = text.replace("\x00", "")
    for key in ("FUTU_LOGIN_PASSWORD", "FUTU_TRD_UNLOCK_PASSWORD", "login_password", "trd_unlock_password"):
        cleaned = cleaned.replace(key, "***")
    return cleaned


def tail(text: str, limit: int) -> str:
    return text[-limit:] if len(text) > limit else text


def emit(ok: bool, message: str, **fields) -> None:
    print(json.dumps({"ok": ok, "message": message, **fields}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
