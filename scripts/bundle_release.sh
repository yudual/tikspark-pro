#!/usr/bin/env bash
set -e

# ==============================================================================
# TikSpark Pro - 发布包一键打包脚本 (本地执行)
# 生成免构建独立发布压缩包 tikspark-pro-release.tar.gz
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> 1. 确保前端已构建最新版本..."
cd frontend
npm ci --silent
npm run build
cd ..

echo "==> 2. 检查后端 Python 语法..."
python3 -m compileall -q backend

echo "==> 3. 打包发布归档文件 (包含预构建前端静态资源)..."
OUTPUT_TAR="tikspark-pro-release.tar.gz"

tar -czf "$OUTPUT_TAR" \
    --exclude='.git' \
    --exclude='.github' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='frontend/node_modules' \
    --exclude='backend/data' \
    --exclude='backups' \
    --exclude='legacy' \
    --exclude='.vscode' \
    --exclude='.DS_Store' \
    --exclude="$OUTPUT_TAR" \
    backend/ \
    frontend/dist/ \
    main.py \
    Dockerfile \
    docker-compose.yml \
    deploy_vps_quick.sh \
    .env.example \
    README.md \
    DEPLOY_VPS.md \
    DEPLOY_1PANEL.md \
    ARCHITECTURE.md

echo "==> 打包完成: $OUTPUT_TAR (体积约 $(du -h "$OUTPUT_TAR" | cut -f1))"
echo "==> 您可以直接将该压缩包上传到任何国内低配 VPS，解压后直接启动即可！"
