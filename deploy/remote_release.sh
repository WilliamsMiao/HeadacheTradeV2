#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/headachetrade}"
APP_USER="${APP_USER:-headachetrade}"
SERVICE_NAME="${SERVICE_NAME:-headachetrade.service}"
ENV_DIR="${ENV_DIR:-/etc/headachetrade}"
RELEASE_ID="${RELEASE_ID:-manual}"
RELEASE_DIR="${APP_ROOT}/releases/${RELEASE_ID}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "remote_release.sh must run as root, usually via sudo" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl nginx sudo

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  install -m 0755 /root/.local/bin/uv /usr/local/bin/uv
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${RELEASE_DIR}" "${APP_ROOT}/shared/data"
tar -xzf - -C "${RELEASE_DIR}"

mkdir -p "${ENV_DIR}"
if [[ ! -f "${ENV_DIR}/headachetrade.env" ]]; then
  install -m 0640 -o root -g "${APP_USER}" "${RELEASE_DIR}/deploy/headachetrade.env.example" "${ENV_DIR}/headachetrade.env"
fi

install -m 0644 "${RELEASE_DIR}/deploy/nginx-headachetrade.conf" /etc/nginx/sites-available/headachetrade
ln -sfn /etc/nginx/sites-available/headachetrade /etc/nginx/sites-enabled/headachetrade
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

chown -R "${APP_USER}:${APP_USER}" "${APP_ROOT}"
ln -sfn "${RELEASE_DIR}" "${APP_ROOT}/current"

install -m 0755 "${RELEASE_DIR}/deploy/opend_admin.py" /usr/local/sbin/headachetrade-opend-admin
cat >/etc/sudoers.d/headachetrade-opend-admin <<EOF
${APP_USER} ALL=(root) NOPASSWD: /usr/local/sbin/headachetrade-opend-admin *
EOF
chmod 0440 /etc/sudoers.d/headachetrade-opend-admin
visudo -cf /etc/sudoers.d/headachetrade-opend-admin

cd "${APP_ROOT}/current"
sudo -u "${APP_USER}" uv sync --frozen --no-dev
sudo -u "${APP_USER}" uv run python -m app.cli init-db

install -m 0644 deploy/headachetrade.service "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager --lines=30

if [[ "${INSTALL_FUTU_OPEND:-1}" == "1" ]]; then
  bash "${RELEASE_DIR}/deploy/install_futu_opend.sh"
fi
