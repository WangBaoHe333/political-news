#!/bin/bash
# 时政系统部署脚本
# 适用于阿里云轻量服务器

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令是否存在
check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "命令 $1 不存在，请先安装"
        exit 1
    fi
}

# 显示帮助
show_help() {
    echo "时政系统部署脚本"
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  init          初始化服务器环境"
    echo "  deploy        部署应用"
    echo "  update        更新应用"
    echo "  backup        备份数据"
    echo "  restore       恢复数据"
    echo "  logs          查看日志"
    echo "  status        查看服务状态"
    echo "  help          显示此帮助信息"
}

# 初始化服务器环境
init_server() {
    log_info "开始初始化服务器环境..."

    # 更新系统
    log_info "更新系统包..."
    sudo apt-get update && sudo apt-get upgrade -y

    # 安装Docker
    if ! command -v docker &> /dev/null; then
        log_info "安装Docker..."
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker $USER
        log_warn "需要重新登录以使Docker组权限生效"
    fi

    # 安装Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_info "安装Docker Compose..."
        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi

    # 安装必要的工具
    log_info "安装必要工具..."
    sudo apt-get install -y curl wget git nginx certbot python3-certbot-nginx

    # 创建项目目录
    log_info "创建项目目录..."
    sudo mkdir -p /opt/political-news
    sudo chown -R $USER:$USER /opt/political-news

    log_info "服务器环境初始化完成！"
}

# 部署应用
deploy_app() {
    log_info "开始部署时政系统..."

    # 进入项目目录
    cd /opt/political-news || {
        log_error "项目目录不存在，请先运行 init"
        exit 1
    }

    # 克隆或更新代码
    if [ -d ".git" ]; then
        log_info "更新代码..."
        git pull origin main
    else
        log_info "克隆代码..."
        git clone https://github.com/WangBaoHe333/political-news.git .
    fi

    # 检查环境变量文件
    if [ ! -f ".env" ]; then
        log_warn "未找到 .env 文件，从示例文件创建..."
        cp .env.example .env
        log_warn "请编辑 .env 文件，设置必要的环境变量（特别是 OPENAI_API_KEY）"
        nano .env || vim .env || vi .env
    fi

    # 构建并启动服务
    log_info "启动Docker服务..."
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d

    # 等待服务启动
    log_info "等待服务启动..."
    sleep 10

    # 检查服务状态
    if docker-compose ps | grep -q "Up"; then
        log_info "服务启动成功！"
        log_info "应用地址: http://$(curl -s ifconfig.me):8000"
        log_info "API文档: http://$(curl -s ifconfig.me):8000/docs"
    else
        log_error "服务启动失败，请查看日志"
        docker-compose logs
        exit 1
    fi

    log_info "部署完成！"
}

# 更新应用
update_app() {
    log_info "更新应用..."

    cd /opt/political-news || {
        log_error "项目目录不存在"
        exit 1
    }

    # 拉取最新代码
    git pull origin main

    # 重启服务
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d

    log_info "应用更新完成！"
}

# 备份数据
backup_data() {
    log_info "备份数据..."

    BACKUP_DIR="/opt/political-news-backup"
    BACKUP_FILE="political-news-backup-$(date +%Y%m%d-%H%M%S).tar.gz"

    mkdir -p $BACKUP_DIR

    # 备份数据库文件
    if [ -f "/opt/political-news/data/political_news.db" ]; then
        cp /opt/political-news/data/political_news.db $BACKUP_DIR/
    fi

    # 备份环境变量
    if [ -f "/opt/political-news/.env" ]; then
        cp /opt/political-news/.env $BACKUP_DIR/
    fi

    # 创建压缩包
    tar -czf $BACKUP_FILE -C $BACKUP_DIR .

    # 上传到远程存储（可选）
    # scp $BACKUP_FILE user@remote-server:/backup/

    log_info "备份完成: $BACKUP_FILE"
    log_info "备份文件保存在当前目录"
}

# 恢复数据
restore_data() {
    log_info "恢复数据..."

    if [ -z "$1" ]; then
        log_error "请指定备份文件"
        echo "用法: $0 restore <备份文件>"
        exit 1
    fi

    BACKUP_FILE=$1

    if [ ! -f "$BACKUP_FILE" ]; then
        log_error "备份文件不存在: $BACKUP_FILE"
        exit 1
    fi

    # 停止服务
    cd /opt/political-news
    docker-compose down

    # 解压备份文件
    TEMP_DIR=$(mktemp -d)
    tar -xzf $BACKUP_FILE -C $TEMP_DIR

    # 恢复数据库
    if [ -f "$TEMP_DIR/political_news.db" ]; then
        cp $TEMP_DIR/political_news.db data/
    fi

    # 恢复环境变量
    if [ -f "$TEMP_DIR/.env" ]; then
        cp $TEMP_DIR/.env .env
    fi

    # 启动服务
    docker-compose up -d

    # 清理临时文件
    rm -rf $TEMP_DIR

    log_info "数据恢复完成！"
}

# 查看日志
show_logs() {
    cd /opt/political-news || {
        log_error "项目目录不存在"
        exit 1
    }

    if [ "$1" = "-f" ]; then
        docker-compose logs -f
    else
        docker-compose logs
    fi
}

# 查看服务状态
show_status() {
    cd /opt/political-news || {
        log_error "项目目录不存在"
        exit 1
    }

    echo "=== Docker容器状态 ==="
    docker-compose ps

    echo ""
    echo "=== 服务健康状态 ==="
    curl -s http://localhost:8000/health || echo "服务不可达"

    echo ""
    echo "=== 磁盘使用情况 ==="
    df -h /opt/political-news

    echo ""
    echo "=== 内存使用情况 ==="
    free -h
}

# 主程序
case "$1" in
    init)
        init_server
        ;;
    deploy)
        deploy_app
        ;;
    update)
        update_app
        ;;
    backup)
        backup_data
        ;;
    restore)
        restore_data "$2"
        ;;
    logs)
        show_logs "$2"
        ;;
    status)
        show_status
        ;;
    help|*)
        show_help
        ;;
esac