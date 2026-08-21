#!/usr/bin/env bash
# 최신 코드로 재배포 (git pull → 재빌드)
#   실행: bash deploy/redeploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/PFM_deploy}"
cd "$APP_DIR"

echo "[1/3] 최신 코드 받기..."
git pull --ff-only

echo "[2/3] 재빌드·기동..."
sudo docker compose up -d --build

echo "[3/3] 미사용 이미지 정리..."
sudo docker image prune -f

echo "재배포 완료. 로그: sudo docker compose logs -f"
