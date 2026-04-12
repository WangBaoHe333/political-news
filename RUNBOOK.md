# RUNBOOK（故障排查手册）

## 0. 先看三项基础状态

```bash
systemctl status political-news.service --no-pager
journalctl -u political-news.service -n 120 --no-pager
curl -s http://127.0.0.1:8000/health
```

## 1. 页面空白 / 无法打开

### 现象
- 浏览器空白
- `curl 127.0.0.1:8000` 连接失败

### 排查
```bash
systemctl status political-news.service --no-pager
journalctl -u political-news.service -n 120 --no-pager
```

### 处理
```bash
systemctl restart political-news.service
ufw allow 8000/tcp || true
```

## 2. 报错 `could not translate host name "postgres"`

### 根因
非 Docker 运行却使用了 Docker 内部主机名 `postgres`。

### 修复
```bash
cd /opt/political-news
sed -i '/^DATABASE_URL=/d' .env.production
echo 'DATABASE_URL=sqlite:///./political_news.db' >> .env.production
systemctl restart political-news.service
```

确认：
```bash
curl -s http://127.0.0.1:8000/health
```

## 3. 同步时间不是北京时间

### 目标
- 系统时区：`Asia/Shanghai`
- 任务时区：`Asia/Shanghai`

### 检查与修复
```bash
timedatectl set-timezone Asia/Shanghai
grep -E "SCHEDULED_SYNC_TIMEZONE|SCHEDULED_SYNC_INTERVAL_HOURS" /opt/political-news/.env.production
systemctl restart political-news.service
```

## 4. 同步显示 fetched>0 但 saved=0

### 常见原因
- 都是重复数据（已存在）
- 日期解析/来源校验未通过被过滤
- 时间范围太窄

### 建议动作
```bash
curl "http://127.0.0.1:8000/sync?months=3&max_items=300&token=<SYNC_ADMIN_TOKEN>"
curl "http://127.0.0.1:8000/sync-status"
```

看近期日志：
```bash
journalctl -u political-news.service -n 200 --no-pager
```

## 5. 2025 年数据覆盖不足

### 说明
部分来源历史页结构会变化，个别月份可能拉取偏少。

### 建议动作
```bash
curl "http://127.0.0.1:8000/sync?year=2025&max_pages=500&max_items=1000&token=<SYNC_ADMIN_TOKEN>"
```

查看 2025 月份分布（SQLite）：
```bash
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('/opt/political-news/political_news.db')
cur = conn.cursor()
for m,c in cur.execute("select month,count(*) from news where year=2025 group by month order by month"):
    print(f"2025-{m:02d}: {c}")
conn.close()
PY
```

## 6. 启动后数据为空

### 检查数据库文件是否存在
```bash
ls -lh /opt/political-news/political_news.db
```

### 手动触发一次同步
```bash
curl "http://127.0.0.1:8000/sync?months=1&max_items=200&token=<SYNC_ADMIN_TOKEN>"
```

## 7. 重建服务（最后手段）

```bash
systemctl stop political-news.service || true
pkill -f "uvicorn app.main:app" || true
systemctl daemon-reload
systemctl reset-failed political-news.service
systemctl enable --now political-news.service
systemctl status political-news.service --no-pager
```

## 8. 运行正常判定

同时满足以下条件：
- `systemctl status` 为 `active (running)`
- `/health` 返回 `status=healthy`
- `/sync-status` 返回正常 JSON（非 500）
- 首页可访问且能看到新闻数据
