#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/political-news}"
SERVICE_NAME="${SERVICE_NAME:-political-news.service}"
RUN_USER="${RUN_USER:-root}"
RUN_GROUP="${RUN_GROUP:-root}"
SYSTEMD_UNIT_DIR="/etc/systemd/system"
TEMPLATE_PATH="${INSTALL_DIR}/scripts/systemd/political-news.service"
RUNTIME_ENV_PATH="${INSTALL_DIR}/.env.runtime"

if [[ ! -d "${INSTALL_DIR}" ]]; then
  echo "错误：目录不存在 ${INSTALL_DIR}" >&2
  exit 1
fi

if [[ ! -x "${INSTALL_DIR}/.venv/bin/uvicorn" ]]; then
  echo "错误：未检测到 ${INSTALL_DIR}/.venv/bin/uvicorn，请先创建虚拟环境并安装依赖。" >&2
  exit 1
fi

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  echo "错误：未检测到 systemd 模板 ${TEMPLATE_PATH}" >&2
  exit 1
fi

mkdir -p "${INSTALL_DIR}/logs"

if [[ -f "${INSTALL_DIR}/.env.production" ]]; then
  cp "${INSTALL_DIR}/.env.production" "${RUNTIME_ENV_PATH}"
elif [[ -f "${INSTALL_DIR}/.env" ]]; then
  cp "${INSTALL_DIR}/.env" "${RUNTIME_ENV_PATH}"
elif [[ -f "${INSTALL_DIR}/.env.example" ]]; then
  cp "${INSTALL_DIR}/.env.example" "${RUNTIME_ENV_PATH}"
fi

if [[ ! -f "${RUNTIME_ENV_PATH}" ]]; then
  cat >"${RUNTIME_ENV_PATH}" <<EOF
DATABASE_URL=sqlite:///./political_news.db
AUTO_SYNC_ON_STARTUP=0
BOOTSTRAP_RECENT_NEWS_ON_STARTUP=0
SCHEDULED_SYNC_INTERVAL_HOURS=1
SCHEDULED_SYNC_TIMEZONE=Asia/Shanghai
EXPOSE_API_DOCS=0
SYNC_ADMIN_TOKEN=change_this_token
HTTP_VERIFY_TLS=1
CORS_ORIGINS=http://39.104.27.129:8000
EOF
fi

tmp_unit="$(mktemp)"
sed \
  -e "s#__RUN_USER__#${RUN_USER}#g" \
  -e "s#__RUN_GROUP__#${RUN_GROUP}#g" \
  -e "s#__INSTALL_DIR__#${INSTALL_DIR}#g" \
  "${TEMPLATE_PATH}" > "${tmp_unit}"

install -m 644 "${tmp_unit}" "${SYSTEMD_UNIT_DIR}/${SERVICE_NAME}"
rm -f "${tmp_unit}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "==> ${SERVICE_NAME} 已安装并重启"
echo "==> 查看状态: systemctl status ${SERVICE_NAME} --no-pager"
echo "==> 查看日志: journalctl -u ${SERVICE_NAME} -n 200 --no-pager"
