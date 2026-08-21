#!/usr/bin/env bash
# 오라클 클라우드 Always Free VM (Ubuntu) 최초 셋업 스크립트
#   실행: bash deploy/oracle-setup.sh
#   사전: OCI 콘솔의 VCN 보안목록에서 Ingress 80,443 (0.0.0.0/0) 허용 규칙 추가
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/AnGyeonheal/PFM_deploy.git}"
APP_DIR="${APP_DIR:-$HOME/PFM_deploy}"

echo "[1/6] 시스템 패키지 업데이트..."
sudo apt-get update -y && sudo apt-get upgrade -y
sudo apt-get install -y git curl ca-certificates

echo "[2/6] Docker 설치..."
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi
sudo systemctl enable --now docker

echo "[3/6] 저장소 클론/갱신..."
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "[4/6] .env 준비..."
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))' 2>/dev/null || openssl rand -hex 32)"
  sed -i "s|^WEB_SECRET_KEY=.*|WEB_SECRET_KEY=${SECRET}|" .env
  echo ">>> .env 를 편집해 GEMINI_API_KEY 와 (도메인 사용 시) SITE_ADDRESS 를 채우세요:  nano .env"
fi

echo "[5/6] 방화벽(HTTP/HTTPS) 개방..."
# Oracle Ubuntu 이미지: iptables 기본. (OCI 보안목록은 콘솔에서 별도 허용 필요)
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
sudo netfilter-persistent save 2>/dev/null || true
# firewalld 계열(Oracle Linux 등) 대응
sudo firewall-cmd --permanent --add-service=http --add-service=https 2>/dev/null || true
sudo firewall-cmd --reload 2>/dev/null || true

echo "[6/6] 컨테이너 빌드·기동..."
sudo docker compose up -d --build

PUB_IP="$(curl -fsSL https://api.ipify.org 2>/dev/null || echo '공인IP')"
echo "─────────────────────────────────────────────"
echo "완료! 접속: http://${PUB_IP}/   (도메인+SITE_ADDRESS 설정 시 https://도메인)"
echo "⚠️  이 VM 공인 IP(${PUB_IP})를 토스 개발자 콘솔에 등록해야 토스 연동이 됩니다."
echo "⚠️  OCI 콘솔 → VCN → 보안목록 → Ingress 80,443 허용 규칙도 확인하세요."
echo "로그: sudo docker compose logs -f"
