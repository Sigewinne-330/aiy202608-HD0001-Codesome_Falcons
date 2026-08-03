#!/bin/bash
set -e

SERVER="root@47.238.153.0"
PROJECT_DIR="/root/ib-assistant"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 同步代码到服务器 ==="
rsync -avz --progress \
  --exclude 'backend/venv' \
  --exclude 'backend/__pycache__' \
  --exclude 'backend/.env' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude '.git' \
  --exclude '.idea' \
  --exclude '.vscode' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$LOCAL_DIR/" "$SERVER:$PROJECT_DIR/"

echo "=== 重新构建并启动 ==="
ssh "$SERVER" "cd $PROJECT_DIR && docker compose up -d --build"

echo "=== 清理旧镜像 ==="
ssh "$SERVER" "docker image prune -f"

echo "=== 部署完成 ==="
echo "访问: http://ibuddy.cc 或 http://47.238.153.0:8081"
