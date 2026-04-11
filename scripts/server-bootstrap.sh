#!/usr/bin/env bash
# 在服务器上首次或重复部署「默认栈」：SQLite + 单应用容器（与 CI 一致）。
# 用法（在服务器上）：
#   curl -fsSL https://raw.githubusercontent.com/WangBaoHe333/political-news/main/scripts/server-bootstrap.sh | bash
# 或本机已能 SSH 时：
#   ssh user@39.104.27.129 'bash -s' < scripts/server-bootstrap.sh
#
# 需要：已安装 Docker 与 Compose v2（docker compose）或 docker-compose；当前用户在 docker 组或有 sudo。

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/political-news}"
REPO_URL="${REPO_URL:-https://github.com/WangBaoHe333/political-news.git}"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 docker，请先安装 Docker。" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "错误：未找到 docker compose 或 docker-compose。" >&2
  exit 1
fi

echo "==> 目录: $INSTALL_DIR"
if [[ ! -d "$INSTALL_DIR" ]]; then
  sudo mkdir -p "$INSTALL_DIR"
  sudo chown -R "$(id -un):$(id -gn)" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

if [[ -d .git ]]; then
  echo "==> git pull"
  git fetch origin
  git checkout main
  git pull origin main
else
  echo "==> git clone"
  git clone "$REPO_URL" .
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
  fi
  echo "" >&2
  echo "请在 $INSTALL_DIR 编辑 .env（按需填写数据库与同步配置），然后执行：" >&2
  echo "  cd $INSTALL_DIR && ${DC[*]} up -d --build" >&2
  exit 2
fi

if [[ ! -f ssl/fullchain.pem ]] || [[ ! -f ssl/privkey.pem ]]; then
  echo "==> 未检测到 SSL 证书，生成自签名证书（浏览器会提示不安全，可日后换 Let's Encrypt）"
  mkdir -p ssl
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout ssl/privkey.pem \
    -out ssl/fullchain.pem \
    -subj "/CN=39.104.27.129" 2>/dev/null
fi

echo "==> 构建并启动容器"
"${DC[@]}" down || true
"${DC[@]}" build --no-cache
"${DC[@]}" up -d

echo "==> 等待健康检查..."
sleep 12
"${DC[@]}" ps

if curl -sf "http://127.0.0.1:8000/health" >/dev/null; then
  echo "==> 本机健康检查通过: http://127.0.0.1:8000/health"
else
  echo "警告：本机 8000 健康检查未通过，请查看日志: ${DC[*]} logs political-news" >&2
fi
