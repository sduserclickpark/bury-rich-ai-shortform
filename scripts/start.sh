#!/bin/sh
# 웹 서버와 백그라운드 워커를 함께 실행한다. 워커가 죽으면 자동으로 다시 시작한다.
set -e
mkdir -p "${DATA_DIR:-/data}"
(
  while true; do
    python -m app.worker || true
    echo "[start.sh] worker exited, restarting in 5s"; sleep 5
  done
) &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
