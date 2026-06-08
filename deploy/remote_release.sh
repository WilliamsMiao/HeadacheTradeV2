#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/headachetrade}"
APP_USER="${APP_USER:-headachetrade}"
SERVICE_NAME="${SERVICE_NAME:-headachetrade.service}"
RELEASE_ID="${RELEASE_ID:-manual}"
RELEASE_DIR="${APP_ROOT}/releases/${RELEASE_ID}"

mkdir -p "${RELEASE_DIR}" "${APP_ROOT}/shared/data"
tar -xzf - -C "${RELEASE_DIR}"

chown -R "${APP_USER}:${APP_USER}" "${APP_ROOT}"
ln -sfn "${RELEASE_DIR}" "${APP_ROOT}/current"

cd "${APP_ROOT}/current"
sudo -u "${APP_USER}" uv sync --frozen --no-dev
sudo -u "${APP_USER}" uv run python -m app.cli init-db

install -m 0644 deploy/headachetrade.service "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager --lines=30

