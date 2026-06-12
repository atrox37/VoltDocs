#!/bin/bash
# VoltDocs 部署脚本
#
# 架构：
#   用户 → 网关机 192.168.30.10:18088 → (端口映射) → 本虚拟机:8088
#
# 使用方式：
#   1. 把项目上传到虚拟机（git clone 或 scp）
#   2. 复制并填写 backend/.env（参考 backend/.env.example）
#   3. sudo bash deploy/setup-https.sh

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# 固定的对外访问地址（通过网关机访问）
GATEWAY_IP="192.168.30.10"
GATEWAY_PORT="18088"
PUBLIC_URL="http://${GATEWAY_IP}:${GATEWAY_PORT}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"
info "项目根目录：$PROJECT_ROOT"

# ── 检查 .env ─────────────────────────────────────────────────────────────────
ENV_FILE="$PROJECT_ROOT/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    warn ".env 不存在，从模板创建"
    cp "$PROJECT_ROOT/backend/.env.example" "$ENV_FILE"
    warn "请先编辑 $ENV_FILE，填入配置后重新运行"
    exit 1
fi

# ── 安装 Docker ───────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "安装 Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    info "Docker 已安装：$(docker --version)"
fi

if ! docker compose version &>/dev/null 2>&1; then
    info "安装 Docker Compose Plugin..."
    apt-get update -y
    apt-get install -y docker-compose-plugin
fi
info "Docker Compose：$(docker compose version)"

# ── 数据目录 ──────────────────────────────────────────────────────────────────
DATA_DIR="/opt/voltdocs/data"
info "创建数据目录：$DATA_DIR"
mkdir -p "$DATA_DIR"/{db,uploads,outputs,templates,jobs}
chmod -R 755 "$DATA_DIR"

# ── 写入生产环境变量到 .env ───────────────────────────────────────────────────
# 仅在尚未设置时自动填入 FRONTEND_URL 和 COGNITO_REDIRECT_URI
if ! grep -q "^FRONTEND_URL=http" "$ENV_FILE" 2>/dev/null; then
    info "自动写入 FRONTEND_URL=${PUBLIC_URL}"
    sed -i "s|^FRONTEND_URL=.*|FRONTEND_URL=${PUBLIC_URL}|" "$ENV_FILE" || \
        echo "FRONTEND_URL=${PUBLIC_URL}" >> "$ENV_FILE"
fi

CALLBACK_URI="${PUBLIC_URL}/api/auth/callback"
if ! grep -q "^COGNITO_REDIRECT_URI=http" "$ENV_FILE" 2>/dev/null; then
    info "自动写入 COGNITO_REDIRECT_URI=${CALLBACK_URI}"
    sed -i "s|^COGNITO_REDIRECT_URI=.*|COGNITO_REDIRECT_URI=${CALLBACK_URI}|" "$ENV_FILE" || \
        echo "COGNITO_REDIRECT_URI=${CALLBACK_URI}" >> "$ENV_FILE"
fi

# ── 构建并启动 ────────────────────────────────────────────────────────────────
info "构建 Docker 镜像..."
docker compose build --no-cache

info "启动服务..."
docker compose up -d

info "等待服务就绪（10s）..."
sleep 10

# ── 健康检查 ──────────────────────────────────────────────────────────────────
info "检查服务状态..."
docker compose ps

if curl -sf http://localhost:8088 > /dev/null 2>&1; then
    info "前端正常 ✓"
else
    warn "前端未响应，检查：docker compose logs web"
fi

if curl -sf http://localhost:8080/api/health > /dev/null 2>&1; then
    info "后端正常 ✓"
else
    warn "后端未响应，检查：docker compose logs api"
fi

# ── 输出摘要 ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  VoltDocs 部署完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  内网访问地址：${PUBLIC_URL}"
echo "  Cognito 回调：${CALLBACK_URI}"
echo ""
echo "请确认以下事项："
echo "  1. 网关机 ${GATEWAY_IP} 已将 ${GATEWAY_PORT} 端口映射到本机 8088"
echo "  2. AWS Cognito 应用客户端回调 URL 已添加：${CALLBACK_URI}"
echo "  3. Cognito 允许的登出 URL 已添加：${PUBLIC_URL}"
echo ""
echo "常用命令："
echo "  查看日志：docker compose logs -f"
echo "  重启：    docker compose restart"
echo "  停止：    docker compose down"
echo "  更新：    git pull && docker compose build && docker compose up -d"
echo ""
echo "数据目录：${DATA_DIR}"
