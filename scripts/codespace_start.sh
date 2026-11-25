#!/bin/bash
# GitHub Codespaces 시작 시 웹 서버 + 워커 자동 실행 (테스트 전용, development 모드)
cd "$(dirname "$0")/.."
export DATA_DIR="$PWD/data" APP_ENV=development
export ADMIN_EMAIL="${ADMIN_EMAIL:-admin@test.local}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-test1234!}"
export WHISPER_MODEL="${WHISPER_MODEL:-base}"
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "app.worker" 2>/dev/null || true
nohup sh scripts/start.sh > data_server.log 2>&1 &
echo "서버 시작: 포트 8000 (관리자 $ADMIN_EMAIL)"
