# 时政系统 (Political News System)

一个帮助考公人和时政爱好者获取最新时政内容的智能平台，提供AI自动总结、考公风格出题、按月份归档等功能。

## ✨ 功能特性

- **时政新闻聚合**：自动从中国政府网(www.gov.cn)抓取时政新闻
- **AI智能分析**：使用OpenAI GPT-4o-mini生成新闻摘要和考公风格题目
- **时间维度展示**：
  - 今日时政（截止目前）
  - 昨日时政
  - 近一年/近两年时政
  - 按年份筛选查看
- **按月归档**：自动按月份分组整理时政内容
- **考公训练**：生成公务员考试风格的练习题（单选、判断、材料概括等）
- **后台同步**：支持定时自动同步和手动批量回填
- **RESTful API**：提供完整的API接口供第三方调用
- **响应式Web界面**：现代化设计，支持移动端访问

## 🚀 快速开始

### 环境要求
- Python 3.9+
- SQLite (默认) / PostgreSQL / MySQL
- OpenAI API Key (用于AI功能)

### 安装步骤

1. **克隆项目**
   ```bash
   git clone https://github.com/WangBaoHe333/political-news.git
   cd political-news
   ```

2. **创建虚拟环境**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   # 或 .venv\Scripts\activate  # Windows
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **配置环境变量**
   ```bash
   cp .env.example .env
   # 编辑 .env 文件，设置你的 OpenAI API Key
   ```

5. **初始化数据库**
   ```bash
   python -c "from app.database import init_db; init_db()"
   ```

6. **启动应用**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

7. **访问应用**
   - Web界面: http://localhost:8000
   - API文档: http://localhost:8000/docs
   - ReDoc文档: http://localhost:8000/redoc

## ⚙️ 配置说明

### 环境变量 (.env)
```env
# 数据库配置
DATABASE_URL=sqlite:///./political_news.db

# OpenAI配置
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_SUMMARY_MODEL=gpt-4o-mini
OPENAI_QUESTION_MODEL=gpt-4o-mini

# 应用配置
AUTO_SYNC_ON_STARTUP=0  # 启动时自动同步（0=禁用，1=启用）
SYNC_MAX_PAGES=260      # 最大抓取页数
SYNC_MAX_ITEMS=400      # 最大抓取条目数
HTTP_TIMEOUT_SECONDS=30 # HTTP请求超时时间

# 数据源配置（通常不需要修改）
LIST_BASE_URL=https://www.gov.cn/yaowen/
LIST_JSON_URL=https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json
```

### 数据库支持
默认使用SQLite，如需使用其他数据库：
- PostgreSQL: `DATABASE_URL=postgresql://user:password@localhost/dbname`
- MySQL: `DATABASE_URL=mysql://user:password@localhost/dbname`

## 📊 数据同步

### 手动同步
1. **近一年数据**：点击"后台同步近一年"按钮
2. **近两年数据**：点击"后台同步近两年"按钮
3. **本年数据**：点击"后台同步本年"按钮
4. **分批回填**：点击"分批回填近两年"（适合大量历史数据）

### 自动同步
- 启动时自动同步：设置 `AUTO_SYNC_ON_STARTUP=1`
- 定时任务：每6小时自动同步最新数据（通过APScheduler）

### 同步状态查看
- 首页显示最近同步结果
- 访问 `/sync-status` 查看详细同步状态

## 🔌 API接口

### 新闻数据API
- `GET /api/news` - 获取新闻列表（可选year参数按年份筛选）
- `GET /api/news/today` - 获取今日时政
- `GET /api/news/yesterday` - 获取昨日时政
- `GET /api/news/grouped-by-month` - 按月分组获取新闻
- `GET /api/news/past-two-years` - 获取过去两年时政内容

### AI 输出 API（与首页同源逻辑）
- `GET /api/ai/summary` - 获取当前筛选范围内的 AI 要点总结（可选 `year` 查询参数，与 `/api/news` 一致）
- `GET /api/ai/questions` - 获取公考风格练习题 JSON（可选 `year`）

### 运维
- `GET /health` - 健康检查（JSON，含 `status` 与 `timestamp`）

### 同步管理API
- `GET /sync` - 手动触发同步
- `GET /sync-status` - 获取同步状态
- `GET /backfill-view` - 触发分批回填

### 响应格式示例
```json
{
  "years": [2024, 2023, 2022],
  "items": [
    {
      "id": 1,
      "title": "新闻标题",
      "link": "https://www.gov.cn/...",
      "summary": "新闻摘要",
      "published": "2024-01-15",
      "published_at": "2024-01-15T00:00:00",
      "source": "gov_cn",
      "category": "时政",
      "year": 2024,
      "month": 1
    }
  ]
}
```

## 🐳 Docker部署

### 构建镜像
```bash
docker build -t political-news .
```

### 运行容器
```bash
docker run -d \
  -p 8000:8000 \
  -e OPENAI_API_KEY=your_api_key \
  -v ./data:/app/data \
  --name political-news \
  political-news
```

### Docker Compose
```yaml
version: '3.8'
services:
  political-news:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///./data/political_news.db
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

## ☁️ 阿里云轻量服务器部署

### 1. 服务器准备
```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# 安装Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### 2. 部署应用
```bash
# 克隆项目
git clone https://github.com/WangBaoHe333/political-news.git
cd political-news

# 配置环境变量
cp .env.example .env
nano .env  # 编辑配置

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 3. 配置域名和SSL（可选）
```bash
# 使用nginx反向代理
sudo apt install nginx certbot python3-certbot-nginx

# 配置nginx
sudo nano /etc/nginx/sites-available/political-news
```

Nginx配置示例：
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🧪 测试

### 运行测试
```bash
# 安装测试依赖
pip install pytest httpx

# 运行测试
pytest tests/
```

### 测试覆盖范围
- 新闻抓取模块测试
- AI分析模块测试
- API端点测试
- 数据库操作测试

## 🐛 故障排除

### 常见问题

1. **数据库表不存在**
   ```bash
   python -c "from app.database import init_db; init_db()"
   ```

2. **OpenAI API调用失败**
   - 检查 `OPENAI_API_KEY` 环境变量
   - 验证API Key是否有足够余额
   - 检查网络连接

3. **新闻抓取失败**
   - 检查网络连接
   - 验证数据源URL是否可访问
   - 查看日志获取详细错误信息

4. **内存不足**
   - 减少 `SYNC_MAX_PAGES` 和 `SYNC_MAX_ITEMS` 值
   - 使用分批回填功能

### 查看日志
```bash
# 查看应用日志
docker-compose logs political-news

# 查看特定服务的日志
docker-compose logs -f app
```

## 🔧 开发

### 项目结构
```
political-news/
├── app/                    # 应用代码
│   ├── __init__.py
│   ├── main.py            # FastAPI主应用
│   ├── models.py          # 数据库模型
│   ├── database.py        # 数据库配置
│   ├── schemas.py         # Pydantic模型
│   ├── fetch_news.py      # 新闻抓取模块
│   ├── ai_summary.py      # AI分析模块
│   └── tasks.py           # 定时任务
├── tests/                 # 测试文件
├── requirements.txt       # Python依赖
├── Dockerfile            # Docker配置
├── docker-compose.yml    # Docker Compose配置
├── .env.example          # 环境变量示例
└── README.md             # 项目说明
```

### 代码规范
- 使用Black进行代码格式化
- 使用isort进行导入排序
- 使用mypy进行类型检查

### 开发命令
```bash
# 代码格式化
black app/

# 导入排序
isort app/

# 类型检查
mypy app/
```

## 🤝 贡献指南

1. Fork本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 🙏 致谢

- 数据来源：[中国政府网](https://www.gov.cn)
- AI能力：[OpenAI GPT](https://openai.com)
- Web框架：[FastAPI](https://fastapi.tiangolo.com)
- 前端设计灵感：多种公务员考试资料网站

## 🛠️ 开发与贡献

### 开发环境设置

```bash
# 1. 克隆仓库
git clone https://github.com/WangBaoHe333/political-news.git
cd political-news

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或 .venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -e ".[dev]"  # 使用pyproject.toml安装所有依赖

# 4. 设置pre-commit钩子
pre-commit install

# 5. 运行测试
pytest
```

### 代码质量工具

项目使用以下工具确保代码质量：

- **Black**: 代码格式化 `black app/ tests/`
- **isort**: 导入排序 `isort app/ tests/`
- **flake8**: 代码规范检查 `flake8 app/`
- **mypy**: 静态类型检查 `mypy app/`
- **bandit**: 安全扫描 `bandit -r app/`

使用pre-commit在提交前自动运行所有检查：

```bash
pre-commit run --all-files
```

### 测试

- **单元测试**: `pytest tests/ -v`
- **覆盖率报告**: `pytest --cov=app --cov-report=html`
- **目标覆盖率**: 80%+

### CI/CD流水线

GitHub Actions自动执行：
1. 代码质量检查 (flake8, mypy, bandit)
2. 单元测试 (pytest with coverage)
3. Docker镜像构建和推送
4. 自动部署到服务器 (main分支)

### 提交代码

1. 创建功能分支: `git checkout -b feature/新功能`
2. 运行测试: `pytest`
3. 格式化代码: `black . && isort .`
4. 提交更改: `git commit -m "描述变更"`
5. 推送到远程: `git push origin feature/新功能`
6. 创建Pull Request

## 📦 发布流程

1. 更新版本号: `pyproject.toml`
2. 更新CHANGELOG.md
3. 创建标签: `git tag -a v1.0.0 -m "版本说明"`
4. 推送标签: `git push origin v1.0.0`
5. GitHub Actions自动构建和发布Docker镜像

## 📞 联系与支持

- 问题反馈：[GitHub Issues](https://github.com/WangBaoHe333/political-news/issues)
- 功能建议：[GitHub Discussions](https://github.com/WangBaoHe333/political-news/discussions)
- 邮件联系：wangbaohe333@gmail.com

---

**提示**：本系统仅供学习和研究使用，请遵守相关法律法规，尊重数据源的使用条款。