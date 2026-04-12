# 时政聚合平台 (Political News)

面向两类用户：
- 考公/考编备考用户（需要稳定、可回看、可检索的时政资料）
- 日常关注时政用户（需要权威来源、更新及时、阅读简洁）

## 在线访问

本项目已部署在线版本，普通用户无需自行部署，直接访问即可：

- 站点首页：`http://39.104.27.129:8000/`
- 同步状态：`http://39.104.27.129:8000/status`

适合直接用于：
- 查看今日时政、昨日时政
- 按分类专题浏览
- 按年份、关键词、月份归档检索
- 日常关注权威时政动态

如后续绑定正式域名，应以正式域名为主，以上服务器地址仅为当前在线入口。

## 免责声明

本项目及其网站内容仅供学习、研究与信息检索参考，不构成任何官方立场或决策依据。  
站内信息来源于公开网站的聚合与索引展示，最终请以各来源站点原文和官方发布为准。  
如有侵权或不当内容，请联系仓库维护者处理。

## 功能概览

- 权威来源聚合：政府网、人民网、新华网、中国新闻网、央视网、外交部等
- 页面导航：今日时政、昨日时政、分类专题、数据源、按月归档、同步状态
- 检索能力：关键词搜索、年份筛选（最低到 2025）、按月归档展开
- 数据策略：每小时自动同步（北京时间），支持手动同步和回填
- 内容策略：保留原文链接，不做 AI 改写
- 终端适配：桌面 + 移动端自适应

## 项目说明

GitHub 仓库主要用于：
- 展示项目源码与功能说明
- 记录更新日志与运维文档
- 维护在线版本

如果你只是想使用网站，请直接访问上方在线地址，不需要自己部署。

## 本地开发（开发者使用）

```bash
git clone https://github.com/WangBaoHe333/political-news.git
cd political-news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

本地启动后可访问：
- 首页：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/health`
- 同步状态：`http://127.0.0.1:8000/status`

## 关键环境变量

见 [.env.example](./.env.example)。

最关键的是：
- `DATABASE_URL`
  - 非 Docker 推荐：`sqlite:///./political_news.db`
  - Docker + postgres：`postgresql://postgres:password@postgres:5432/political_news`
- `SCHEDULED_SYNC_INTERVAL_HOURS=1`
- `SCHEDULED_SYNC_TIMEZONE=Asia/Shanghai`
- `SYNC_ADMIN_TOKEN=<长随机字符串>`

## 部署说明（仅维护者使用）

推荐使用 `systemd + uvicorn + sqlite`（网络稳定、排障简单）。

完整步骤见 [DEPLOY.md](./DEPLOY.md)。

## 常用同步接口

生产环境如果配置了 `SYNC_ADMIN_TOKEN`，调用需带 `token` 或请求头 `X-Sync-Token`。

- 手动同步近 N 月：
  - `GET /sync?months=3&max_items=300&token=...`
- 手动同步某年：
  - `GET /sync?year=2026&max_items=500&token=...`
- 查看同步状态：
  - `GET /sync-status`
- 分批回填（页面入口）：
  - `GET /backfill-view?months=24&batch_size=2&max_items=120&token=...`

## 排障入口

常见问题（空白页、数据库连接到 `postgres` 失败、时区不对、同步失败）见 [RUNBOOK.md](./RUNBOOK.md)。

## 测试

```bash
pytest -q
```

## License

MIT
