#!/usr/bin/env bash
# ============================================================
# Ecommerce Agent 一键安装脚本 (Linux / macOS)
# 用法: chmod +x setup.sh && ./setup.sh
# ============================================================
set -euo pipefail

# ---------- 颜色输出 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

# ============================================================
# Step 0: 欢迎
# ============================================================
echo ""
echo "=============================================="
echo "  Ecommerce Agent 一键安装向导"
echo "=============================================="
echo ""

# ============================================================
# Step 1: 检测 Python 版本 (需要 3.11+)
# ============================================================
info "检测 Python 版本..."

PYTHON_CMD=""
for cmd in python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    err "未找到 Python 3.11+，请先安装："
    echo "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv python3.11-dev"
    echo "  CentOS/RHEL:   sudo yum install python3.11 python3.11-devel"
    echo "  macOS:         brew install python@3.11"
    echo "  或从 https://www.python.org/downloads/ 下载"
    exit 1
fi

ok "Python: $PYTHON_CMD ($($PYTHON_CMD --version))"

# ============================================================
# Step 2: 检测系统依赖
# ============================================================
info "检测系统依赖..."

MISSING_DEPS=()

# 检测 build-essential / gcc
if ! command -v gcc &>/dev/null; then
    MISSING_DEPS+=("gcc/build-essential")
fi

# 检测 libopenblas (FAISS 需要)
OPENBLAS_OK=false
if ldconfig -p 2>/dev/null | grep -q openblas; then
    OPENBLAS_OK=true
elif [[ -f /usr/lib/libopenblas.so ]] || [[ -f /usr/lib/x86_64-linux-gnu/libopenblas.so ]]; then
    OPENBLAS_OK=true
elif [[ "$(uname)" == "Darwin" ]]; then
    # macOS 上通过 brew 安装的 openblas
    if brew list openblas &>/dev/null 2>&1; then
        OPENBLAS_OK=true
    fi
fi

if [[ "$OPENBLAS_OK" == "false" ]]; then
    MISSING_DEPS+=("libopenblas")
fi

if [[ ${#MISSING_DEPS[@]} -gt 0 ]]; then
    warn "缺少系统依赖: ${MISSING_DEPS[*]}"
    echo ""
    echo "  请根据系统执行对应命令："
    echo ""
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        case "$ID" in
            ubuntu|debian)
                echo "    sudo apt update && sudo apt install -y build-essential libopenblas-dev"
                ;;
            centos|rhel|fedora)
                echo "    sudo yum install -y gcc gcc-c++ openblas-devel"
                echo "    # 或 Fedora: sudo dnf install -y gcc gcc-c++ openblas-devel"
                ;;
            *)
                echo "    sudo apt install -y build-essential libopenblas-dev   # Debian 系"
                echo "    sudo yum install -y gcc gcc-c++ openblas-devel       # RedHat 系"
                ;;
        esac
    elif [[ "$(uname)" == "Darwin" ]]; then
        echo "    xcode-select --install"
        echo "    brew install openblas"
    else
        echo "    请安装 gcc 和 openblas 开发库"
    fi
    echo ""
    read -rp "是否已安装完成？按 Enter 继续，或 Ctrl+C 退出后安装..." _
else
    ok "系统依赖检测通过"
fi

# ============================================================
# Step 3: 创建虚拟环境
# ============================================================
info "配置 Python 虚拟环境..."

if [[ -d "$VENV_DIR" ]]; then
    ok "虚拟环境已存在: $VENV_DIR"
else
    # 优先使用 conda
    if command -v conda &>/dev/null; then
        info "检测到 conda，使用 conda 创建环境..."
        conda create -n feishuagent python=3.11 -y 2>/dev/null || {
            warn "conda 创建失败，回退到 venv..."
            $PYTHON_CMD -m venv "$VENV_DIR"
        }
        if conda env list | grep -q feishuagent; then
            # conda 环境创建成功
            eval "$(conda shell.bash hook)"
            conda activate feishuagent
            ok "conda 环境 feishuagent 已创建并激活"
        else
            $PYTHON_CMD -m venv "$VENV_DIR"
            source "$VENV_DIR/bin/activate"
            ok "venv 虚拟环境已创建: $VENV_DIR"
        fi
    else
        $PYTHON_CMD -m venv "$VENV_DIR"
        ok "venv 虚拟环境已创建: $VENV_DIR"
    fi
fi

# 激活虚拟环境（如果还没激活）
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
elif command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate feishuagent 2>/dev/null || true
fi

# ============================================================
# Step 4: 安装 Python 依赖
# ============================================================
info "安装 Python 依赖（这可能需要几分钟）..."

pip install --upgrade pip -q

# 优先使用 uv（更快）
if command -v uv &>/dev/null; then
    info "检测到 uv，使用 uv 安装依赖..."
    uv pip install -r "$PROJECT_DIR/requirements.txt"
else
    pip install -r "$PROJECT_DIR/requirements.txt"
fi

ok "Python 依赖安装完成"

# ============================================================
# Step 5: 配置环境变量
# ============================================================
info "配置环境变量..."

if [[ -f "$ENV_FILE" ]]; then
    warn ".env 文件已存在，跳过配置（如需重新配置请删除 .env 后重试）"
else
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    ok "已从 .env.example 复制为 .env"
    echo ""
    echo "  ===================================================="
    echo "  请编辑 .env 文件，填入以下必填配置："
    echo "  ===================================================="
    echo ""
    echo "  必填项："
    echo "    LLM_API_KEY        - 大模型 API 密钥"
    echo "                         (DashScope: https://dashscope.console.aliyun.com/)"
    echo "    FEISHU_APP_ID      - 飞书应用 ID"
    echo "    FEISHU_APP_SECRET  - 飞书应用密钥"
    echo "    API_KEY            - HTTP 接口鉴权密钥（自定义一个随机字符串）"
    echo ""
    echo "  可选项："
    echo "    ROUTER_API_KEY     - 路由专用模型密钥（留空复用 LLM_API_KEY）"
    echo "    VLM_API_KEY        - 多模态视觉模型密钥（留空复用 LLM_API_KEY）"
    echo ""
    echo "  配置文件位置: $ENV_FILE"
    echo ""
    echo "  飞书开放平台配置: https://open.feishu.cn/app"
    echo "    1. 创建企业自建应用"
    echo "    2. 添加权限: im:message:readonly, im:message:send_as_bot 等"
    echo "    3. 事件订阅: 选择长连接模式，订阅 im.message.receive_v1"
    echo "    4. 发布应用"
    echo ""

    read -rp "是否现在编辑 .env 文件？[Y/n] " edit_env
    if [[ "${edit_env,,}" != "n" ]]; then
        ${EDITOR:-nano} "$ENV_FILE"
    fi
fi

# ============================================================
# Step 6: 初始化数据库
# ============================================================
info "初始化数据库..."
cd "$PROJECT_DIR"
$PYTHON_CMD scripts/init_db.py
ok "数据库初始化完成"

# ============================================================
# Step 7: 创建数据目录
# ============================================================
info "创建数据目录..."
mkdir -p "$PROJECT_DIR/data/uploads"
mkdir -p "$PROJECT_DIR/data/vectorstore"
mkdir -p "$PROJECT_DIR/data/documents"
mkdir -p "$PROJECT_DIR/data/reports"
ok "数据目录创建完成"

# ============================================================
# Step 8: 创建启动脚本
# ============================================================
info "创建快捷启动脚本..."

cat > "$PROJECT_DIR/start.sh" << 'STARTEOF'
#!/usr/bin/env bash
# Ecommerce Agent 快捷启动脚本
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 激活虚拟环境
if [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
    source "$PROJECT_DIR/.venv/bin/activate"
elif command -v conda &>/dev/null; then
    eval "$(conda shell.bash hook)"
    conda activate feishuagent 2>/dev/null || true
fi

MODE="${1:-dev}"

case "$MODE" in
    dev|develop)
        echo "[INFO] 启动开发模式 (热重载)..."
        uvicorn app.main:app --reload --host 127.0.0.1 --port ${APP_PORT:-8000}
        ;;
    prod|production)
        echo "[INFO] 启动生产模式..."
        uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8000} --workers 1
        ;;
    *)
        echo "用法: ./start.sh [dev|prod]"
        echo "  dev  - 开发模式 (热重载, 默认)"
        echo "  prod - 生产模式"
        exit 1
        ;;
esac
STARTEOF
chmod +x "$PROJECT_DIR/start.sh"
ok "启动脚本已创建: start.sh"

# ============================================================
# 完成
# ============================================================
echo ""
echo "=============================================="
echo -e "  ${GREEN}安装完成！${NC}"
echo "=============================================="
echo ""
echo "  后续步骤："
echo "    1. 编辑配置: nano .env  (填入 API 密钥等)"
echo "    2. 启动服务: ./start.sh        (开发模式)"
echo "                 ./start.sh prod   (生产模式)"
echo "    3. 访问服务: http://localhost:8000"
echo "    4. 健康检查: curl http://localhost:8000/health"
echo ""
echo "  常用命令："
echo "    查看日志:   终端输出即为日志"
echo "    停止服务:   Ctrl+C"
echo "    RAG 评估:   python -m app.rag.eval.evaluate_rag"
echo "    运行测试:   pytest tests/"
echo ""
