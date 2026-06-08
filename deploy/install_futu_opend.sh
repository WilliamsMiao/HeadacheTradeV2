#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${FUTU_OPEND_ROOT:-/opt/futu-opend}"
SERVICE_NAME="${FUTU_OPEND_SERVICE:-futu-opend.service}"
SERVICE_USER="${FUTU_OPEND_USER:-futuopend}"
ENV_DIR="${FUTU_OPEND_ENV_DIR:-/etc/futu-opend}"
ENV_FILE="${ENV_DIR}/futu-opend.env"
DOWNLOAD_URL="${FUTU_OPEND_DOWNLOAD_URL:-https://www.futunn.com/download/fetch-lasted-link?name=opend-ubuntu}"
FALLBACK_DOWNLOAD_URL="${FUTU_OPEND_FALLBACK_DOWNLOAD_URL:-https://softwaredownload.futunn.com/Futu_OpenD_10.7.6708_Ubuntu18.04.tar.gz}"
FORCE_UPDATE="${FUTU_OPEND_FORCE_UPDATE:-0}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install_futu_opend.sh must run as root, usually via sudo" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gzip iproute2 procps tar

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

mkdir -p "${INSTALL_ROOT}/releases" "${ENV_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat >"${ENV_FILE}" <<'EOF'
# Futu OpenD credentials are intentionally kept on the server, not in Git.
# Fill these values on the server, then run: systemctl restart futu-opend
FUTU_LOGIN_ACCOUNT=
FUTU_LOGIN_PASSWORD=

# Optional: if you enable remote operation/trade unlock in your OpenD setup.
FUTU_TRD_UNLOCK_PASSWORD=
EOF
  chmod 0640 "${ENV_FILE}"
  chown root:"${SERVICE_USER}" "${ENV_FILE}"
fi

if [[ "${FORCE_UPDATE}" != "1" && -x "${INSTALL_ROOT}/current/FutuOpenD" ]]; then
  echo "Futu OpenD already installed at ${INSTALL_ROOT}/current/FutuOpenD"
else
  workdir="$(mktemp -d)"
  archive="${workdir}/futu-opend.tar.gz"
  release_dir="${INSTALL_ROOT}/releases/$(date -u +%Y%m%d%H%M%S)"

  echo "Downloading Futu OpenD from ${DOWNLOAD_URL}"
  if ! curl -fL --retry 3 --connect-timeout 20 -A "Mozilla/5.0" "${DOWNLOAD_URL}" -o "${archive}"; then
    echo "Primary download failed; trying fallback ${FALLBACK_DOWNLOAD_URL}"
    curl -fL --retry 3 --connect-timeout 20 -A "Mozilla/5.0" "${FALLBACK_DOWNLOAD_URL}" -o "${archive}"
  fi

  mkdir -p "${release_dir}"
  tar -xzf "${archive}" -C "${release_dir}"
  bin_path="$(find "${release_dir}" -type f -name FutuOpenD | head -n 1)"
  if [[ -z "${bin_path}" ]]; then
    echo "FutuOpenD binary not found after extracting archive" >&2
    exit 1
  fi

  chmod +x "${bin_path}"
  ln -sfn "$(dirname "${bin_path}")" "${INSTALL_ROOT}/current"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_ROOT}"
  rm -rf "${workdir}"
fi

cat >/usr/local/bin/futu-opend-start <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

cd /opt/futu-opend/current

args=()
if [[ -n "${FUTU_LOGIN_ACCOUNT:-}" ]]; then
  args+=("-login_account" "${FUTU_LOGIN_ACCOUNT}")
fi
if [[ -n "${FUTU_LOGIN_PASSWORD:-}" ]]; then
  args+=("-login_pwd" "${FUTU_LOGIN_PASSWORD}")
fi
if [[ -n "${FUTU_TRD_UNLOCK_PASSWORD:-}" ]]; then
  args+=("-trd_unlock_pwd" "${FUTU_TRD_UNLOCK_PASSWORD}")
fi

exec ./FutuOpenD "${args[@]}"
EOF
chmod 0755 /usr/local/bin/futu-opend-start

cat >"/etc/systemd/system/${SERVICE_NAME}" <<EOF
[Unit]
Description=Futu OpenD
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_ROOT}/current
EnvironmentFile=-${ENV_FILE}
ExecStart=/usr/local/bin/futu-opend-start
Restart=on-failure
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

if systemctl restart "${SERVICE_NAME}"; then
  echo "Futu OpenD service restarted"
else
  echo "Futu OpenD service did not start cleanly. Fill ${ENV_FILE} and restart ${SERVICE_NAME}." >&2
fi

systemctl status "${SERVICE_NAME}" --no-pager --lines=40 || true
ss -ltnp | grep ':11111' || true
