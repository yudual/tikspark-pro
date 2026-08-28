#!/usr/bin/env bash
set -e

# ==============================================================================
# TikSpark Pro - 国内低配 VPS 快速极速部署脚本 (免前端构建 / 国内镜像加速)
# 针对阿里云/腾讯云 1C1G / 1C2G 等低配、小带宽、弱 IO 机器深度优化
# ==============================================================================

echo "=================================================="
echo "    TikSpark Pro 国内低配 VPS 极速安装助手       "
echo "=================================================="

# 0. 检查并配置 Swap 虚拟内存 (防止 1C1G/2C2G 弱机 Chromium 内存毛刺 OOM 强杀)
SWAP_TOTAL=$(free -m 2>/dev/null | awk '/Swap:/ {print $2}' || echo "0")
if [ "${SWAP_TOTAL:-0}" -lt 512 ] && [ "$(id -u)" -eq 0 -o -n "$(command -v sudo)" ]; then
    echo "[+] 检测到当前机器 Swap < 512MB，正在配置 1.5GB 虚拟内存以防止 OOM 崩溃..."
    if [ ! -f /swapfile ]; then
        (sudo fallocate -l 1.5G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=1536) && \
        sudo chmod 600 /swapfile && \
        sudo mkswap /swapfile && \
        sudo swapon /swapfile 2>/dev/null || true
        echo "[✓] 1.5GB Swap 虚拟内存挂载成功。"
    fi
fi

# 1. 检查 Python 3

if ! command -v python3 &>/dev/null; then
    echo "[!] 未检测到 Python 3，正在安装系统依赖..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v yum &>/dev/null; then
        sudo yum install -y python3 python3-pip
    fi
fi

# 2. 创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "[+] 创建独立虚拟环境 .venv..."
    python3 -m venv .venv
fi

# 3. 使用清华源高速安装后端依赖 (避免外网超时)
echo "[+] 使用清华 PyPI 镜像安装后端依赖..."
.venv/bin/pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r backend/requirements.txt

# 4. 配置国内淘宝镜像安装 Playwright Chromium (节省 70% 下载时间与磁盘空间)
echo "[+] 配置国内 npmmirror 镜像高速下载 Playwright Chromium 内核..."
export PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/
.venv/bin/python -m playwright install chromium

# 如果是 Ubuntu/Debian 系统，自动补全浏览器运行库依赖
if command -v apt-get &>/dev/null; then
    echo "[+] 安装 Playwright 基础系统依赖库..."
    sudo .venv/bin/python -m playwright install-deps chromium || true
fi

# 5. 检查预构建前端静态资源
if [ ! -d "frontend/dist" ] || [ ! -f "frontend/dist/index.html" ]; then
    echo "[!] 警告: 未找到 frontend/dist 预构建静态文件！"
    echo "[!] 若您的 VPS 内存小于 2G，不建议在 VPS 上执行 npm build。"
    echo "[!] 请在本地打包后上传，或从发布包中解压。"
else
    echo "[✓] 前端预构建静态文件已就绪 (免编译，极大节省内存与 IO)。"
fi

# 6. 配置管理员令牌
ADMIN_TOKEN="${TIKSPARK_ADMIN_TOKEN:-}"
if [ -z "$ADMIN_TOKEN" ]; then
    # 生成 16 位随机令牌
    ADMIN_TOKEN=$(head -c 16 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)
    echo "=================================================="
    echo "  [重要] 已为您自动生成管理员令牌: $ADMIN_TOKEN"
    echo "  访问网页版右上角请填入此令牌进行解锁。"
    echo "=================================================="
fi

echo ""
echo "=================================================="
echo " 安装完成！您可以使用以下命令启动服务："
echo "=================================================="
echo " 方式 1: 直接前台启动："
echo "   TIKSPARK_ADMIN_TOKEN=$ADMIN_TOKEN .venv/bin/python main.py"
echo ""
echo " 方式 2: 后台后台守护启动 (nohup)："
echo "   nohup env TIKSPARK_ADMIN_TOKEN=$ADMIN_TOKEN .venv/bin/python main.py > tikspark.log 2>&1 &"
echo "=================================================="
