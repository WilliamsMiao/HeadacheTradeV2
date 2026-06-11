#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/headachetrade}"
APP_USER="${APP_USER:-headachetrade}"
SERVICE_NAME="${SERVICE_NAME:-headachetrade.service}"
ENV_DIR="${ENV_DIR:-/etc/headachetrade}"
RELEASE_ID="${RELEASE_ID:-manual}"
RELEASE_DIR="${APP_ROOT}/releases/${RELEASE_ID}"
CURRENT_LINK="${APP_ROOT}/current"
BACKUP_DIR="${APP_ROOT}/shared/backups"

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

mkdir -p "${RELEASE_DIR}" "${APP_ROOT}/shared/data" "${BACKUP_DIR}"
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

install -m 0755 "${RELEASE_DIR}/deploy/opend_admin.py" /usr/local/sbin/headachetrade-opend-admin
cat >/etc/sudoers.d/headachetrade-opend-admin <<EOF
${APP_USER} ALL=(root) NOPASSWD: /usr/local/sbin/headachetrade-opend-admin *
EOF
chmod 0440 /etc/sudoers.d/headachetrade-opend-admin
visudo -cf /etc/sudoers.d/headachetrade-opend-admin

cd "${RELEASE_DIR}"
sudo -u "${APP_USER}" uv sync --frozen --no-dev

set -a
# shellcheck disable=SC1090
source "${ENV_DIR}/headachetrade.env"
set +a

if [[ "${DATABASE_URL:-}" == sqlite:///* ]]; then
  database_path="${DATABASE_URL#sqlite:///}"
  if [[ -f "${database_path}" ]]; then
    backup_path="${BACKUP_DIR}/headache_trade_${RELEASE_ID}.sqlite3"
    python3 - "${database_path}" "${backup_path}" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
    chown "${APP_USER}:${APP_USER}" "${backup_path}"
    find "${BACKUP_DIR}" -type f -name 'headache_trade_*.sqlite3' -printf '%T@ %p\n' \
      | sort -nr \
      | tail -n +11 \
      | cut -d' ' -f2- \
      | xargs -r rm -f
  fi
fi

mkdir -p "${RELEASE_DIR}/.uv-cache"
chown "${APP_USER}:${APP_USER}" "${RELEASE_DIR}/.uv-cache"
sudo -u "${APP_USER}" env \
  DATABASE_URL="${DATABASE_URL:-sqlite:////opt/headachetrade/shared/data/headache_trade.sqlite3}" \
  UV_CACHE_DIR="${RELEASE_DIR}/.uv-cache" \
  uv run python -m app.cli init-db

previous_release="$(readlink -f "${CURRENT_LINK}" || true)"
ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

install -m 0644 deploy/headachetrade.service "/etc/systemd/system/${SERVICE_NAME}"
install -m 0644 deploy/headachetrade-daily.service /etc/systemd/system/headachetrade-daily.service
install -m 0644 deploy/headachetrade-daily.timer /etc/systemd/system/headachetrade-daily.timer
install -m 0644 deploy/headachetrade-60m.service /etc/systemd/system/headachetrade-60m.service
install -m 0644 deploy/headachetrade-60m.timer /etc/systemd/system/headachetrade-60m.timer
install -m 0644 deploy/headachetrade-sim-loop.service /etc/systemd/system/headachetrade-sim-loop.service
install -m 0644 deploy/headachetrade-sim-loop.timer /etc/systemd/system/headachetrade-sim-loop.timer
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl enable --now headachetrade-daily.timer headachetrade-60m.timer
if ! grep -q '^ENABLE_SIM_TRADING=' "${ENV_DIR}/headachetrade.env"; then
  printf '\nENABLE_SIM_TRADING=true\nENABLE_REAL_TRADING=false\n' >>"${ENV_DIR}/headachetrade.env"
fi
if grep -Eq '^ENABLE_SIM_TRADING=(true|1|yes)$' "${ENV_DIR}/headachetrade.env"; then
  systemctl enable --now headachetrade-sim-loop.timer
else
  systemctl disable --now headachetrade-sim-loop.timer || true
fi
if ! systemctl restart "${SERVICE_NAME}"; then
  if [[ -n "${previous_release}" && -d "${previous_release}" ]]; then
    ln -sfn "${previous_release}" "${CURRENT_LINK}"
    systemctl restart "${SERVICE_NAME}" || true
  fi
  systemctl status "${SERVICE_NAME}" --no-pager --lines=50 || true
  exit 1
fi

healthy=0
for _ in $(seq 1 20); do
  if curl --fail --silent --show-error http://127.0.0.1:8001/health >/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done

if [[ "${healthy}" != "1" ]]; then
  echo "New release failed health check; rolling back application symlink" >&2
  if [[ -n "${previous_release}" && -d "${previous_release}" ]]; then
    ln -sfn "${previous_release}" "${CURRENT_LINK}"
    systemctl restart "${SERVICE_NAME}" || true
  fi
  systemctl status "${SERVICE_NAME}" --no-pager --lines=50 || true
  exit 1
fi

systemctl status "${SERVICE_NAME}" --no-pager --lines=30

if [[ "${INSTALL_FUTU_OPEND:-1}" == "1" ]]; then
  bash "${RELEASE_DIR}/deploy/install_futu_opend.sh"
fi
