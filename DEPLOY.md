# DEPLOY（服务器部署手册）

本文是“服务器实操版”，默认环境：
- Ubuntu 22.04+
- 项目目录：`/opt/political-news`
- 运行方式：`systemd + uvicorn + sqlite`

## 1. 首次部署

```bash
apt update && apt install -y git python3 python3-venv python3-pip ca-certificates
mkdir -p /opt/political-news
```

将代码上传到服务器（任选一种）：
- `git clone`（仓库可访问时）
- `rsync` 从本地上传

进入目录后：

```bash
cd /opt/political-news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.production
```

编辑 `.env.production`（至少确认）：

```env
DATABASE_URL=sqlite:///./political_news.db
SCHEDULED_SYNC_INTERVAL_HOURS=1
SCHEDULED_SYNC_TIMEZONE=Asia/Shanghai
SYNC_ADMIN_TOKEN=请设置长随机字符串
EXPOSE_API_DOCS=0
```

## 2. 安装 systemd 服务

```bash
cat >/etc/systemd/system/political-news.service <<'EOF'
[Unit]
Description=Political News FastAPI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/political-news
Environment=PYTHONUNBUFFERED=1
Environment=TZ=Asia/Shanghai
Environment=DATABASE_URL=sqlite:///./political_news.db
Environment=SCHEDULED_SYNC_TIMEZONE=Asia/Shanghai
EnvironmentFile=-/opt/political-news/.env.production
ExecStart=/opt/political-news/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now political-news.service
```

## 3. 验证

```bash
systemctl status political-news.service --no-pager
journalctl -u political-news.service -n 120 --no-pager
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/sync-status
```

浏览器访问：
- `http://<服务器IP>:8000/`

放行端口（如需）：

```bash
ufw allow 8000/tcp || true
```

## 4. 更新发布

本地改完代码后，用 `rsync` 上传（推荐）：

```bash
rsync -av --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  /Users/wbh/political-news/ \
  root@<服务器IP>:/opt/political-news/
```

服务器重启服务：

```bash
cd /opt/political-news
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart political-news.service
systemctl status political-news.service --no-pager
```

## 5. 常用运维命令

```bash
# 看日志
journalctl -u political-news.service -f

# 看是否在运行
systemctl is-active political-news.service

# 触发手动同步（示例）
curl "http://127.0.0.1:8000/sync?months=3&max_items=300&token=<SYNC_ADMIN_TOKEN>"

# 查看同步状态
curl "http://127.0.0.1:8000/sync-status"
```

## 6. Docker 模式说明

如果你用 Docker Compose + `postgres` 服务，`DATABASE_URL` 可使用 `@postgres`。
如果你是 systemd 直接跑 uvicorn，必须使用本机可达数据库（推荐 sqlite），不要写 `@postgres`。
