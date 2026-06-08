#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-headachetrade}"
APP_ROOT="${APP_ROOT:-/opt/headachetrade}"
ENV_DIR="${ENV_DIR:-/etc/headachetrade}"
SERVICE_NAME="${SERVICE_NAME:-headachetrade.service}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run as root: sudo bash deploy/install_server.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl rsync nginx

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  install -m 0755 /root/.local/bin/uv /usr/local/bin/uv
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_ROOT}/releases" "${APP_ROOT}/shared/data" "${ENV_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_ROOT}"

if [[ ! -f "${ENV_DIR}/headachetrade.env" ]]; then
  install -m 0640 -o root -g "${APP_USER}" deploy/headachetrade.env.example "${ENV_DIR}/headachetrade.env"
fi

install -m 0644 deploy/headachetrade.service "/etc/systemd/system/${SERVICE_NAME}"
install -m 0644 deploy/nginx-headachetrade.conf /etc/nginx/sites-available/headachetrade
ln -sfn /etc/nginx/sites-available/headachetrade /etc/nginx/sites-enabled/headachetrade
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
nginx -t
systemctl enable nginx
systemctl restart nginx

cat <<MSG
Server bootstrap complete.

Next steps:
1. Put application code at ${APP_ROOT}/current, or let GitHub Actions deploy it.
2. Review ${ENV_DIR}/headachetrade.env.
3. Ensure Futu OpenD is running on FUTU_HOST:FUTU_PORT if you want live data sync on the server.
4. Start or restart with: systemctl restart ${SERVICE_NAME}
MSG

